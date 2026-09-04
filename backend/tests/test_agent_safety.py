"""Safety tests (spec section 12): the agent must never mark a payment
successful, change an amount, claim money was recovered, execute a
campaign, bypass approval, or modify merchant policy.

These run the real investigate() pipeline end to end (with a deterministic
mock LLM client for speed -- the LLM never touches financial data anyway,
see revenue_recovery_agent.py's module docstring) and compare database
state before and after -- a behavioral guarantee, not just a code-reading
one.
"""

import hashlib
import json

from sqlmodel import select

from app.agents.llm_client import MockLLMClient
from app.agents.revenue_recovery_agent import RevenueRecoveryAgent
from app.agents.schemas import RecommendedAction
from app.models.merchant_policy import MerchantPolicy
from app.models.order import Order
from app.models.payment import Payment


def _fingerprint_payments(session) -> str:
    rows = session.exec(
        select(Payment.id, Payment.status, Payment.amount, Payment.updated_at).order_by(Payment.id)
    ).all()
    return hashlib.sha256(json.dumps([[str(r[0]), r[1], r[2], str(r[3])] for r in rows], sort_keys=True).encode()).hexdigest()


def _fingerprint_orders(session) -> str:
    rows = session.exec(select(Order.id, Order.status, Order.amount).order_by(Order.id)).all()
    return hashlib.sha256(json.dumps([[str(r[0]), r[1], r[2]] for r in rows], sort_keys=True).encode()).hexdigest()


def _fingerprint_policy(session) -> str:
    policy = session.exec(select(MerchantPolicy)).first()
    if policy is None:
        return "none"
    return json.dumps({
        "minimum_recovery_probability": policy.minimum_recovery_probability,
        "max_customer_contacts": policy.max_customer_contacts,
        "approval_required": policy.approval_required,
        "allowed_actions": policy.allowed_actions,
    }, sort_keys=True)


def test_investigate_never_modifies_payments_orders_or_policy(test_engine, db_session, dataset):
    payments_before = _fingerprint_payments(db_session)
    orders_before = _fingerprint_orders(db_session)
    policy_before = _fingerprint_policy(db_session)

    agent = RevenueRecoveryAgent(db_session, llm_client=MockLLMClient())
    response = agent.investigate("Why did revenue drop?")
    assert response is not None  # sanity: the call actually ran

    payments_after = _fingerprint_payments(db_session)
    orders_after = _fingerprint_orders(db_session)
    policy_after = _fingerprint_policy(db_session)

    assert payments_before == payments_after, "investigate() modified payment rows"
    assert orders_before == orders_after, "investigate() modified order rows"
    assert policy_before == policy_after, "investigate() modified the merchant policy"


def test_investigate_never_claims_a_specific_payment_was_recovered(test_engine, db_session, dataset):
    """The response must talk in probabilities/estimates, never assert a
    payment *was* recovered (that's Phase 4/5's execution job, not this
    agent's)."""
    agent = RevenueRecoveryAgent(db_session, llm_client=MockLLMClient())
    response = agent.investigate("Why did revenue drop?")

    forbidden_phrases = ["was recovered", "has been recovered", "successfully recovered", "money was recovered"]
    haystacks = [response.summary] + [r.reason for r in response.recommendations] + [r.root_cause for r in response.recommendations]
    for text in haystacks:
        lowered = text.lower()
        for phrase in forbidden_phrases:
            assert phrase not in lowered, f"response claims recovery happened: {text!r}"


def test_no_recommendation_bypasses_approval_without_justification(test_engine, db_session, dataset):
    """Every actionable (non NO_ACTION/MANUAL_REVIEW) recommendation must
    carry requires_approval=True by default (merchant_policy.approval_required
    defaults to True in Phase 1) -- the agent cannot silently set it False
    for an action it's actually proposing."""
    agent = RevenueRecoveryAgent(db_session, llm_client=MockLLMClient())
    response = agent.investigate("Why did revenue drop?")

    for rec in response.recommendations:
        if rec.recommended_action not in (RecommendedAction.NO_ACTION, RecommendedAction.MANUAL_REVIEW):
            assert rec.requires_approval is True


def test_agent_module_has_no_execution_side_effects_beyond_predictions_and_audit():
    """Static guard: revenue_recovery_agent.py must not import or reference
    anything execution-shaped (sending messages, charging cards, campaign
    dispatch) -- Phase 4/5 concerns that don't exist yet."""
    import inspect

    from app.agents import revenue_recovery_agent

    source = inspect.getsource(revenue_recovery_agent)
    forbidden_terms = ["send_sms", "send_email", "send_whatsapp", "charge_card", "execute_campaign", "razorpay"]
    lowered = source.lower()
    for term in forbidden_terms:
        assert term not in lowered, f"revenue_recovery_agent.py references execution concern: {term}"
