"""Policy-enforcement tests for InterventionPlanner -- these use hand-built
findings/opportunities (not the full pipeline) so behavior at each decision
boundary is deterministic and isolated from what anomalies happen to be in
the seeded dataset."""

import uuid

import pytest

from app.agents.revenue_recovery_agent import LOW_CONFIDENCE_THRESHOLD, InterventionPlanner, _cap_by_customer
from app.agents.schemas import Finding, RecommendedAction, Severity
from app.models.merchant_policy import MerchantPolicy


def _finding(revenue_at_risk=100000.0, recoverable=70000.0) -> Finding:
    return Finding(
        finding="Test finding", severity=Severity.HIGH, evidence=["evidence line"],
        affected_payment_count=10, revenue_at_risk=revenue_at_risk,
        estimated_recoverable_revenue=recoverable,
    )


def _opportunity(customer_id=None, probability=0.9, confidence=0.8, expected_recovery=9000.0) -> dict:
    return {
        "payment_id": str(uuid.uuid4()),
        "customer_id": customer_id or str(uuid.uuid4()),
        "amount": 10000.0,
        "recovery_probability": probability,
        "expected_recovery": expected_recovery,
        "confidence": confidence,
        "segment": "HIGH_RECOVERY",
    }


def _policy(**overrides) -> MerchantPolicy:
    defaults = dict(
        merchant_id=uuid.uuid4(), minimum_recovery_probability=0.65, max_customer_contacts=1,
        max_campaign_amount=None, approval_required=True, allowed_actions=["email", "sms", "whatsapp"],
    )
    defaults.update(overrides)
    return MerchantPolicy(**defaults)


def test_no_opportunities_yields_no_action():
    planner = InterventionPlanner()
    decision = planner.plan(_finding(), [], _policy())
    assert decision.recommended_action == RecommendedAction.NO_ACTION
    assert decision.expected_recovery == 0.0
    assert decision.requires_approval is False


def test_high_confidence_above_threshold_yields_payment_link():
    planner = InterventionPlanner()
    opportunities = [_opportunity(probability=0.9, confidence=0.85) for _ in range(3)]
    decision = planner.plan(_finding(), opportunities, _policy(minimum_recovery_probability=0.65))
    assert decision.recommended_action == RecommendedAction.PAYMENT_LINK
    assert decision.expected_recovery > 0
    assert decision.requires_approval is True  # policy.approval_required=True


def test_low_confidence_yields_manual_review_not_automated_action():
    """Spec section 9: below the confidence threshold, never recommend an
    automated intervention -- MANUAL_REVIEW instead."""
    planner = InterventionPlanner()
    low_confidence = LOW_CONFIDENCE_THRESHOLD - 0.05
    opportunities = [_opportunity(probability=0.9, confidence=low_confidence) for _ in range(3)]
    decision = planner.plan(_finding(), opportunities, _policy())
    assert decision.recommended_action == RecommendedAction.MANUAL_REVIEW
    assert decision.expected_recovery == 0.0


def test_probability_below_policy_threshold_yields_manual_review():
    planner = InterventionPlanner()
    opportunities = [_opportunity(probability=0.4, confidence=0.7) for _ in range(3)]
    decision = planner.plan(_finding(), opportunities, _policy(minimum_recovery_probability=0.8))
    assert decision.recommended_action == RecommendedAction.MANUAL_REVIEW


def test_empty_allowed_actions_blocks_to_no_action():
    """Spec section 8: if policy blocks the recommendation, NO_ACTION with
    an explanation -- here, the merchant has disabled all outreach channels."""
    planner = InterventionPlanner()
    opportunities = [_opportunity(probability=0.9, confidence=0.85)]
    decision = planner.plan(_finding(), opportunities, _policy(allowed_actions=[]))
    assert decision.recommended_action == RecommendedAction.NO_ACTION
    assert "channel" in decision.reason.lower()


def test_missing_policy_falls_back_to_default_threshold():
    """No merchant_policy row at all -- must not crash, uses the documented default."""
    planner = InterventionPlanner()
    opportunities = [_opportunity(probability=0.9, confidence=0.85)]
    decision = planner.plan(_finding(), opportunities, None)
    assert decision.recommended_action == RecommendedAction.PAYMENT_LINK


def test_max_customer_contacts_caps_recommendations():
    same_customer = str(uuid.uuid4())
    opportunities = [
        _opportunity(customer_id=same_customer, probability=0.9, confidence=0.85, expected_recovery=9000.0),
        _opportunity(customer_id=same_customer, probability=0.9, confidence=0.85, expected_recovery=8000.0),
        _opportunity(customer_id=str(uuid.uuid4()), probability=0.9, confidence=0.85, expected_recovery=7000.0),
    ]
    capped = _cap_by_customer(opportunities, max_contacts=1)
    assert len(capped) == 2  # one per distinct customer
    customer_ids = [o["customer_id"] for o in capped]
    assert len(customer_ids) == len(set(customer_ids))


def test_max_customer_contacts_reflected_in_expected_recovery():
    same_customer = str(uuid.uuid4())
    opportunities = [
        _opportunity(customer_id=same_customer, probability=0.9, confidence=0.85, expected_recovery=9000.0),
        _opportunity(customer_id=same_customer, probability=0.9, confidence=0.85, expected_recovery=8000.0),
    ]
    planner = InterventionPlanner()
    decision = planner.plan(_finding(), opportunities, _policy(max_customer_contacts=1))
    # Only the first (higher expected_recovery) opportunity for this customer should count.
    assert decision.expected_recovery == pytest.approx(9000.0)
    assert "capped" in decision.reason.lower()
