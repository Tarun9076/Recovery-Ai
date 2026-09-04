"""Service-level tests for the campaign lifecycle. Predictions are
monkeypatched to fixed values keyed by payment_id -- this isolates policy/
workflow correctness from the ML model's actual (data-dependent) output,
which Phase 2's own tests already cover."""

import uuid

import pytest
from sqlmodel import select

from app.models.enums import (
    AuditEventType,
    CampaignStatus,
    OpportunityStatus,
    RecommendedAction,
    RecoveryActionStatus,
)
from app.models.audit_log import AuditLog
from app.models.merchant_policy import MerchantPolicy
from app.models.recovery_action import RecoveryAction
from app.models.recovery_opportunity import RecoveryOpportunity
from app.services import campaign_service, recovery_predictor
from app.services.payment_provider import PaymentProvider


def _patch_predictions(monkeypatch, mapping: dict):
    def fake_predict_recovery(payment_id, session):
        return mapping[payment_id]
    monkeypatch.setattr(recovery_predictor, "predict_recovery", fake_predict_recovery)


def _prediction(probability=0.9, confidence=0.8, amount=1000.0):
    return {
        "recovery_probability": probability,
        "expected_recovery": amount * probability,
        "confidence": confidence,
    }


def _two_failed_payment_ids(dataset, n=2):
    return [dataset.payment_failures[i]["payment_id"] for i in range(n)]


class _AlwaysFailingProvider(PaymentProvider):
    def create_recovery_link(self, **kwargs):
        raise RuntimeError("simulated provider outage")


# -- create_campaign ---------------------------------------------------

def test_create_campaign_happy_path(db_session, dataset, clean_campaign_state, monkeypatch):
    payment_ids = _two_failed_payment_ids(dataset, 2)
    _patch_predictions(monkeypatch, {pid: _prediction(0.9, 0.8) for pid in payment_ids})

    campaign, excluded = campaign_service.create_campaign(
        db_session, name="Test", payment_ids=payment_ids, created_by="tester",
    )
    assert campaign.status == CampaignStatus.PENDING_APPROVAL
    assert campaign.target_count == 2
    assert excluded == []

    actions = db_session.exec(select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)).all()
    assert len(actions) == 2
    assert all(a.status == RecoveryActionStatus.PENDING for a in actions)

    opportunities = db_session.exec(
        select(RecoveryOpportunity).where(RecoveryOpportunity.payment_id.in_(payment_ids))
    ).all()
    assert all(o.status == OpportunityStatus.REVIEWED for o in opportunities)


def test_create_campaign_excludes_low_probability_payments(db_session, dataset, clean_campaign_state, monkeypatch):
    good, bad = _two_failed_payment_ids(dataset, 2)
    _patch_predictions(monkeypatch, {good: _prediction(0.9), bad: _prediction(0.3)})

    campaign, excluded = campaign_service.create_campaign(
        db_session, name="Test", payment_ids=[good, bad], created_by="tester",
    )
    assert campaign.target_count == 1
    assert len(excluded) == 1
    assert excluded[0]["payment_id"] == str(bad)


def test_create_campaign_raises_when_nothing_qualifies(db_session, dataset, clean_campaign_state, monkeypatch):
    payment_ids = _two_failed_payment_ids(dataset, 2)
    _patch_predictions(monkeypatch, {pid: _prediction(0.1) for pid in payment_ids})

    with pytest.raises(campaign_service.CampaignValidationError):
        campaign_service.create_campaign(db_session, name="Test", payment_ids=payment_ids, created_by="tester")


def test_create_campaign_never_trusts_a_stale_opportunity_row(db_session, dataset, clean_campaign_state, monkeypatch):
    """Pre-seed a wrong/stale opportunity (as if from a previous run) with
    an inflated probability, then confirm campaign creation recomputes
    fresh from the (mocked) model rather than reading the stale row."""
    payment_id = _two_failed_payment_ids(dataset, 1)[0]
    payment = next(p for p in dataset.payments if p["id"] == payment_id)

    stale = RecoveryOpportunity(
        payment_id=payment_id, customer_id=payment["customer_id"],
        recovery_probability=0.99, expected_recovery=999999.0,
        recommended_action=RecommendedAction.PAYMENT_LINK, reason="stale", confidence=0.99,
    )
    db_session.add(stale)
    db_session.commit()

    _patch_predictions(monkeypatch, {payment_id: _prediction(0.1, amount=payment["amount"])})

    with pytest.raises(campaign_service.CampaignValidationError):
        campaign_service.create_campaign(db_session, name="Test", payment_ids=[payment_id], created_by="tester")


def test_create_campaign_enforces_max_campaign_amount(db_session, dataset, clean_campaign_state, monkeypatch):
    payment_ids = _two_failed_payment_ids(dataset, 2)
    _patch_predictions(monkeypatch, {pid: _prediction(0.9, amount=100000.0) for pid in payment_ids})

    policy = db_session.exec(select(MerchantPolicy)).first()
    original_cap = policy.max_campaign_amount
    policy.max_campaign_amount = 1.0  # anything will exceed this
    db_session.add(policy)
    db_session.commit()

    try:
        with pytest.raises(campaign_service.CampaignValidationError):
            campaign_service.create_campaign(db_session, name="Test", payment_ids=payment_ids, created_by="tester")
    finally:
        policy.max_campaign_amount = original_cap
        db_session.add(policy)
        db_session.commit()


def test_create_campaign_caps_same_customer_within_batch(db_session, dataset, clean_campaign_state, monkeypatch):
    """Two failed payments from the same customer, both individually
    qualifying -- max_customer_contacts=1 must keep only one."""
    # payment_failures dicts don't carry customer_id directly -- resolve via payments.
    pf_payment_ids = [pf["payment_id"] for pf in dataset.payment_failures[:30]]
    by_customer: dict = {}
    for pid in pf_payment_ids:
        payment = next(p for p in dataset.payments if p["id"] == pid)
        by_customer.setdefault(payment["customer_id"], []).append(pid)
    pair = next((ids for ids in by_customer.values() if len(ids) >= 2), None)
    if pair is None:
        pytest.skip("no customer with 2+ failed payments in this seeded sample")
    pair = pair[:2]

    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in pair})

    campaign, excluded = campaign_service.create_campaign(
        db_session, name="Test", payment_ids=pair, created_by="tester",
    )
    assert campaign.target_count == 1
    assert len(excluded) == 1
    assert "max_customer_contacts" in excluded[0]["reason"]


# -- approve_campaign ----------------------------------------------------

def test_approve_campaign_executes_and_completes(db_session, dataset, clean_campaign_state, monkeypatch):
    payment_ids = _two_failed_payment_ids(dataset, 2)
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign, _ = campaign_service.create_campaign(
        db_session, name="Test", payment_ids=payment_ids, created_by="tester",
    )

    approved = campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner")

    assert approved.status == CampaignStatus.COMPLETED
    assert approved.approved_by == "owner"
    assert approved.approved_at is not None
    assert approved.completed_at is not None

    actions = db_session.exec(select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)).all()
    assert all(a.status == RecoveryActionStatus.EXECUTED for a in actions)
    assert all(a.provider_response and a.provider_response.get("success") for a in actions)

    opportunities = db_session.exec(
        select(RecoveryOpportunity).where(RecoveryOpportunity.payment_id.in_(payment_ids))
    ).all()
    assert all(o.status == OpportunityStatus.EXECUTED for o in opportunities)


def test_approve_campaign_with_failing_provider_marks_failed(db_session, dataset, clean_campaign_state, monkeypatch):
    payment_ids = _two_failed_payment_ids(dataset, 2)
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign, _ = campaign_service.create_campaign(
        db_session, name="Test", payment_ids=payment_ids, created_by="tester",
    )

    approved = campaign_service.approve_campaign(
        db_session, campaign.id, approved_by="owner", provider=_AlwaysFailingProvider(),
    )

    assert approved.status == CampaignStatus.FAILED
    actions = db_session.exec(select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)).all()
    assert all(a.status == RecoveryActionStatus.FAILED for a in actions)
    assert all(a.provider_response and a.provider_response.get("success") is False for a in actions)


def test_cannot_approve_already_approved_campaign(db_session, dataset, clean_campaign_state, monkeypatch):
    payment_ids = _two_failed_payment_ids(dataset, 1)
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign, _ = campaign_service.create_campaign(
        db_session, name="Test", payment_ids=payment_ids, created_by="tester",
    )
    campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner")

    with pytest.raises(campaign_service.CampaignStateError):
        campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner")


def test_approve_nonexistent_campaign_raises(db_session):
    with pytest.raises(campaign_service.CampaignNotFoundError):
        campaign_service.approve_campaign(db_session, uuid.uuid4(), approved_by="owner")


def test_execute_campaign_refuses_a_non_approved_campaign(db_session, dataset, clean_campaign_state, monkeypatch):
    """Defensive guard: even called directly (bypassing approve_campaign),
    _execute_campaign must refuse a campaign that isn't APPROVED -- spec:
    'No campaign executes without approval.'"""
    payment_ids = _two_failed_payment_ids(dataset, 1)
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign, _ = campaign_service.create_campaign(
        db_session, name="Test", payment_ids=payment_ids, created_by="tester",
    )
    assert campaign.status == CampaignStatus.PENDING_APPROVAL

    from app.services.payment_provider import MockPaymentProvider
    with pytest.raises(campaign_service.CampaignStateError):
        campaign_service._execute_campaign(db_session, campaign, provider=MockPaymentProvider())


# -- reject_campaign -------------------------------------------------------

def test_reject_campaign_cancels_and_cascades(db_session, dataset, clean_campaign_state, monkeypatch):
    payment_ids = _two_failed_payment_ids(dataset, 2)
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign, _ = campaign_service.create_campaign(
        db_session, name="Test", payment_ids=payment_ids, created_by="tester",
    )

    rejected = campaign_service.reject_campaign(
        db_session, campaign.id, rejected_by="owner", reason="not this month",
    )
    assert rejected.status == CampaignStatus.CANCELLED
    assert rejected.rejection_reason == "not this month"

    opportunities = db_session.exec(
        select(RecoveryOpportunity).where(RecoveryOpportunity.payment_id.in_(payment_ids))
    ).all()
    assert all(o.status == OpportunityStatus.REJECTED for o in opportunities)

    actions = db_session.exec(select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)).all()
    assert all(a.status == RecoveryActionStatus.FAILED for a in actions)


def test_cannot_reject_a_completed_campaign(db_session, dataset, clean_campaign_state, monkeypatch):
    payment_ids = _two_failed_payment_ids(dataset, 1)
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign, _ = campaign_service.create_campaign(
        db_session, name="Test", payment_ids=payment_ids, created_by="tester",
    )
    campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner")

    with pytest.raises(campaign_service.CampaignStateError):
        campaign_service.reject_campaign(db_session, campaign.id, rejected_by="owner", reason="too late")


# -- audit log -------------------------------------------------------------

def test_full_lifecycle_writes_expected_audit_events(db_session, dataset, clean_campaign_state, monkeypatch):
    payment_ids = _two_failed_payment_ids(dataset, 1)
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign, _ = campaign_service.create_campaign(
        db_session, name="Test", payment_ids=payment_ids, created_by="tester",
    )
    campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner")

    events = db_session.exec(select(AuditLog.event_type)).all()
    assert AuditEventType.CAMPAIGN_CREATED in events
    assert AuditEventType.POLICY_CHECKED in events
    assert AuditEventType.CAMPAIGN_APPROVED in events
    assert AuditEventType.RECOVERY_ACTION_AUTHORIZED in events
    assert AuditEventType.RECOVERY_ACTION_EXECUTED in events

    # The spec's event names are lowercase snake_case -- verify the *stored*
    # value, not just the Python enum member, matches exactly.
    created_row = db_session.exec(select(AuditLog).where(AuditLog.event_type == AuditEventType.CAMPAIGN_CREATED)).first()
    assert created_row.event_type.value == "campaign_created"


# -- safety: no money marked recovered --------------------------------------

def test_no_status_ever_becomes_recovered(db_session, dataset, clean_campaign_state, monkeypatch):
    """Spec section 11: only a real payment confirmation can produce
    recovered_amount. create_campaign/approve_campaign alone (no webhook
    involved) must never set RECOVERED -- that transition only happens in
    webhook_service.process_razorpay_webhook (see test_webhook_service.py),
    triggered by a cryptographically verified inbound event, never here."""
    payment_ids = _two_failed_payment_ids(dataset, 2)
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign, _ = campaign_service.create_campaign(
        db_session, name="Test", payment_ids=payment_ids, created_by="tester",
    )
    campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner")

    opportunities = db_session.exec(
        select(RecoveryOpportunity).where(RecoveryOpportunity.payment_id.in_(payment_ids))
    ).all()
    assert all(o.status != OpportunityStatus.RECOVERED for o in opportunities)

    assert not hasattr(campaign, "recovered_amount")


# -- idempotency (spec section 7) -------------------------------------------

def test_cannot_select_a_payment_with_an_in_flight_action(db_session, dataset, clean_campaign_state, monkeypatch):
    """A payment already in a PENDING_APPROVAL campaign (action status
    PENDING) must be excluded from a second campaign."""
    payment_id = _two_failed_payment_ids(dataset, 1)[0]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})

    first_campaign, _ = campaign_service.create_campaign(
        db_session, name="First", payment_ids=[payment_id], created_by="tester",
    )
    assert first_campaign.target_count == 1

    with pytest.raises(campaign_service.CampaignValidationError):
        campaign_service.create_campaign(
            db_session, name="Second", payment_ids=[payment_id], created_by="tester",
        )


def test_cannot_select_an_already_executed_payment(db_session, dataset, clean_campaign_state, monkeypatch):
    payment_id = _two_failed_payment_ids(dataset, 1)[0]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})

    campaign, _ = campaign_service.create_campaign(
        db_session, name="First", payment_ids=[payment_id], created_by="tester",
    )
    campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner")

    with pytest.raises(campaign_service.CampaignValidationError):
        campaign_service.create_campaign(
            db_session, name="Second", payment_ids=[payment_id], created_by="tester",
        )


def test_can_retry_a_payment_whose_only_action_failed(db_session, dataset, clean_campaign_state, monkeypatch):
    """Spec section 7: a duplicate is prevented *unless* explicitly retried
    after a failed attempt -- a FAILED action must not block a new one."""
    from app.services.payment_provider import PaymentProvider

    class _FailingProvider(PaymentProvider):
        def create_recovery_link(self, **kwargs):
            raise RuntimeError("simulated failure")

    payment_id = _two_failed_payment_ids(dataset, 1)[0]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})

    campaign, _ = campaign_service.create_campaign(
        db_session, name="First", payment_ids=[payment_id], created_by="tester",
    )
    campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner", provider=_FailingProvider())

    actions = db_session.exec(select(RecoveryAction).where(RecoveryAction.payment_id == payment_id)).all()
    assert all(a.status == RecoveryActionStatus.FAILED for a in actions)

    # Retry: a second campaign for the same payment must now be allowed.
    retry_campaign, excluded = campaign_service.create_campaign(
        db_session, name="Retry", payment_ids=[payment_id], created_by="tester",
    )
    assert retry_campaign.target_count == 1
    assert excluded == []


def test_create_campaign_excludes_a_non_executable_recommended_action(db_session, dataset, clean_campaign_state, monkeypatch):
    """Integration-level regression test for the reported bug, at the real
    `create_campaign` entry point (not just the RecoveryActionSelector unit
    tests) -- a high-probability CARD_LIMIT failure must be excluded with
    its real recommended action in the reason, never silently included as a
    payment link the way it was before this fix."""
    upi_payment_id = dataset.payment_failures[0]["payment_id"]  # UPI_FAILURE -- executable
    card_limit_payment_id = dataset.payment_failures[3]["payment_id"]  # CARD_LIMIT -- not executable
    _patch_predictions(monkeypatch, {
        upi_payment_id: _prediction(0.9),
        card_limit_payment_id: _prediction(0.9),
    })

    campaign, excluded = campaign_service.create_campaign(
        db_session, name="Mixed categories", payment_ids=[upi_payment_id, card_limit_payment_id],
        created_by="tester",
    )

    assert campaign.target_count == 1
    included_action = db_session.exec(
        select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)
    ).one()
    assert included_action.payment_id == upi_payment_id
    assert included_action.action_type == RecommendedAction.PAYMENT_LINK

    assert len(excluded) == 1
    assert excluded[0]["payment_id"] == str(card_limit_payment_id)
    assert "ALTERNATIVE_PAYMENT_METHOD" in excluded[0]["reason"]
    assert "not currently executable" in excluded[0]["reason"]


def test_already_recovered_payment_is_not_selectable_into_a_new_campaign(db_session, dataset, clean_campaign_state, monkeypatch):
    """Idempotency (spec section 6/10): a payment already RECOVERED must
    stay excluded from a fresh campaign, exactly like an in-flight one."""
    payment_id = _two_failed_payment_ids(dataset, 1)[0]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})

    campaign, _ = campaign_service.create_campaign(
        db_session, name="Original", payment_ids=[payment_id], created_by="tester",
    )
    campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner")

    action = db_session.exec(select(RecoveryAction).where(RecoveryAction.payment_id == payment_id)).one()
    action.status = RecoveryActionStatus.RECOVERED
    action.recovered_amount = action.provider_response and 1000.0
    db_session.add(action)
    db_session.commit()

    with pytest.raises(campaign_service.CampaignValidationError):
        campaign_service.create_campaign(
            db_session, name="Duplicate", payment_ids=[payment_id], created_by="tester",
        )
