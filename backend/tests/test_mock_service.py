"""Tests for mock_service.py (spec section 8)."""

import uuid

import pytest
from sqlmodel import select

from app.core.config import get_settings
from app.models.enums import (
    CampaignStatus,
    OpportunityStatus,
    RecommendedAction,
    RecoveryActionStatus,
)
from app.models.recovery_action import RecoveryAction
from app.models.recovery_campaign import RecoveryCampaign
from app.models.recovery_opportunity import RecoveryOpportunity
from app.services.mock_service import (
    SimulationNotAllowedError,
    SimulationNotFoundError,
    SimulationStateError,
    simulate_payment,
)


def _seed_action(session, dataset, status=RecoveryActionStatus.EXECUTED, provider_response=True, payment_index=0):
    payment = dataset.payments[payment_index]
    campaign = RecoveryCampaign(
        merchant_id=dataset.merchant["id"], name="mock-fixture", target_count=1,
        total_amount=payment["amount"], expected_recovery=payment["amount"] * 0.8,
        created_by="tester", status=CampaignStatus.COMPLETED,
    )
    session.add(campaign)
    opportunity = RecoveryOpportunity(
        payment_id=payment["id"], customer_id=payment["customer_id"],
        recovery_probability=0.8, expected_recovery=payment["amount"] * 0.8,
        recommended_action=RecommendedAction.PAYMENT_LINK, reason="fixture", confidence=0.7,
        status=OpportunityStatus.EXECUTED,
    )
    session.add(opportunity)
    session.commit()
    session.refresh(campaign)
    session.refresh(opportunity)

    action = RecoveryAction(
        campaign_id=campaign.id, opportunity_id=opportunity.id, payment_id=payment["id"],
        customer_id=payment["customer_id"], action_type=RecommendedAction.PAYMENT_LINK,
        status=status, payment_link_id="plink_mocktest" if provider_response else None,
        provider_response={"success": True, "payment_link_id": "plink_mocktest", "payment_link": "https://x", "status": "created"} if provider_response else None,
    )
    session.add(action)
    session.commit()
    session.refresh(action)
    return action, payment


def test_simulate_payment_happy_path(db_session, dataset, clean_campaign_state):
    action, payment = _seed_action(db_session, dataset)
    result = simulate_payment(db_session, action.id)

    assert result["simulated"] is True
    assert result["status"] == "recovered"
    assert result["amount_paid"] == pytest.approx(payment["amount"])

    db_session.refresh(action)
    assert action.status == RecoveryActionStatus.RECOVERED
    assert action.recovered_amount == pytest.approx(payment["amount"])


def test_simulate_payment_with_custom_amount(db_session, dataset, clean_campaign_state):
    action, _ = _seed_action(db_session, dataset)
    result = simulate_payment(db_session, action.id, amount=42.5)
    assert result["amount_paid"] == 42.5


def test_simulate_payment_blocked_outside_mock_mode(db_session, dataset, clean_campaign_state, monkeypatch):
    action, _ = _seed_action(db_session, dataset)
    monkeypatch.setenv("RAZORPAY_MODE", "test")
    get_settings.cache_clear()
    try:
        with pytest.raises(SimulationNotAllowedError):
            simulate_payment(db_session, action.id)
    finally:
        get_settings.cache_clear()


def test_simulate_payment_unknown_action(db_session):
    with pytest.raises(SimulationNotFoundError):
        simulate_payment(db_session, uuid.uuid4())


def test_simulate_payment_wrong_status(db_session, dataset, clean_campaign_state):
    action, _ = _seed_action(db_session, dataset, status=RecoveryActionStatus.PENDING)
    with pytest.raises(SimulationStateError):
        simulate_payment(db_session, action.id)


def test_simulate_payment_missing_link_id(db_session, dataset, clean_campaign_state):
    action, _ = _seed_action(db_session, dataset, provider_response=False)
    with pytest.raises(SimulationStateError):
        simulate_payment(db_session, action.id)


def test_simulate_payment_twice_does_not_double_count(db_session, dataset, clean_campaign_state):
    action, payment = _seed_action(db_session, dataset)
    simulate_payment(db_session, action.id)

    with pytest.raises(SimulationStateError):
        simulate_payment(db_session, action.id)  # now RECOVERED, not EXECUTED

    db_session.refresh(action)
    assert action.recovered_amount == pytest.approx(payment["amount"])


def test_simulate_payment_writes_audit_log(db_session, dataset, clean_campaign_state):
    from app.models.audit_log import AuditLog
    from app.models.enums import AuditEventType

    action, _ = _seed_action(db_session, dataset)
    simulate_payment(db_session, action.id)

    entry = db_session.exec(
        select(AuditLog).where(AuditLog.entity_id == action.id, AuditLog.event_type == AuditEventType.RECOVERY_CONFIRMED)
    ).first()
    assert entry is not None
    assert entry.actor == "razorpay"  # the webhook pipeline's actor, even for a simulated delivery
