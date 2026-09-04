"""Unit tests for PolicyEngine -- spec section 8: "No campaign may bypass
this service," so every check is tested directly and in isolation."""

import uuid

from app.models.enums import CampaignStatus, OpportunityStatus, RecommendedAction, RecoveryActionStatus
from app.models.merchant_policy import MerchantPolicy
from app.models.recovery_action import RecoveryAction
from app.models.recovery_campaign import RecoveryCampaign
from app.models.recovery_opportunity import RecoveryOpportunity
from app.services.policy_engine import PolicyEngine


def _real_campaign_and_opportunity(session, dataset, *, payment_id, customer_id):
    """RecoveryAction has real FKs to recovery_campaigns/recovery_opportunities
    -- these helpers create minimal valid parents rather than random UUIDs."""
    campaign = RecoveryCampaign(
        merchant_id=dataset.merchant["id"], name="fixture", target_count=1,
        total_amount=100.0, expected_recovery=50.0, created_by="tester",
        status=CampaignStatus.PENDING_APPROVAL,
    )
    session.add(campaign)
    opportunity = RecoveryOpportunity(
        payment_id=payment_id, customer_id=customer_id,
        recovery_probability=0.9, expected_recovery=90.0,
        recommended_action=RecommendedAction.PAYMENT_LINK, reason="fixture",
        confidence=0.8, status=OpportunityStatus.NEW,
    )
    session.add(opportunity)
    session.commit()
    session.refresh(campaign)
    session.refresh(opportunity)
    return campaign, opportunity


def _policy(**overrides) -> MerchantPolicy:
    defaults = dict(
        merchant_id=uuid.uuid4(), minimum_recovery_probability=0.65, max_customer_contacts=1,
        max_campaign_amount=None, approval_required=True, allowed_actions=["email", "sms", "whatsapp"],
    )
    defaults.update(overrides)
    return MerchantPolicy(**defaults)


def test_check_recovery_probability_passes_above_threshold(db_session):
    engine = PolicyEngine(db_session)
    result = engine.check_recovery_probability(0.8, _policy(minimum_recovery_probability=0.65))
    assert result.passed is True


def test_check_recovery_probability_fails_below_threshold(db_session):
    engine = PolicyEngine(db_session)
    result = engine.check_recovery_probability(0.5, _policy(minimum_recovery_probability=0.65))
    assert result.passed is False
    assert "0.65" not in result.reason  # formatted as a percentage, not a raw fraction
    assert "65%" in result.reason


def test_check_recovery_probability_falls_back_without_policy(db_session):
    engine = PolicyEngine(db_session)
    assert engine.check_recovery_probability(0.7, None).passed is True
    assert engine.check_recovery_probability(0.5, None).passed is False


def test_check_allowed_action_fails_when_no_channels(db_session):
    engine = PolicyEngine(db_session)
    result = engine.check_allowed_action(_policy(allowed_actions=[]))
    assert result.passed is False


def test_check_allowed_action_passes_with_channels(db_session):
    engine = PolicyEngine(db_session)
    result = engine.check_allowed_action(_policy(allowed_actions=["email"]))
    assert result.passed is True


def test_check_campaign_limit_passes_with_no_cap(db_session):
    engine = PolicyEngine(db_session)
    result = engine.check_campaign_limit(1_000_000.0, _policy(max_campaign_amount=None))
    assert result.passed is True


def test_check_campaign_limit_enforces_cap(db_session):
    engine = PolicyEngine(db_session)
    policy = _policy(max_campaign_amount=10000.0)
    assert engine.check_campaign_limit(9999.0, policy).passed is True
    assert engine.check_campaign_limit(10001.0, policy).passed is False


def test_check_approval_requires_approved_status_and_approver(db_session, dataset):
    from app.models.recovery_campaign import RecoveryCampaign

    engine = PolicyEngine(db_session)
    pending = RecoveryCampaign(
        merchant_id=dataset.merchant["id"], name="x", target_count=1, total_amount=100.0,
        expected_recovery=50.0, created_by="tester", status=CampaignStatus.PENDING_APPROVAL,
    )
    assert engine.check_approval(pending).passed is False

    approved = RecoveryCampaign(
        merchant_id=dataset.merchant["id"], name="x", target_count=1, total_amount=100.0,
        expected_recovery=50.0, created_by="tester", status=CampaignStatus.APPROVED, approved_by="owner",
    )
    assert engine.check_approval(approved).passed is True


def test_check_customer_contact_limit_ignores_pending_and_failed(db_session, dataset, clean_campaign_state):
    customer_id = dataset.customers[0]["id"]
    payment_id = next(p["id"] for p in dataset.payments if p["customer_id"] == customer_id)
    campaign, opportunity = _real_campaign_and_opportunity(db_session, dataset, payment_id=payment_id, customer_id=customer_id)

    for status in (RecoveryActionStatus.PENDING, RecoveryActionStatus.FAILED):
        db_session.add(RecoveryAction(
            campaign_id=campaign.id, opportunity_id=opportunity.id, payment_id=payment_id,
            customer_id=customer_id, action_type=RecommendedAction.PAYMENT_LINK, status=status,
        ))
    db_session.commit()

    engine = PolicyEngine(db_session)
    result = engine.check_customer_contact_limit(customer_id, _policy(max_customer_contacts=1))
    assert result.passed is True, "PENDING/FAILED actions must not count as an actual contact"


def test_check_customer_contact_limit_counts_executed(db_session, dataset, clean_campaign_state):
    customer_id = dataset.customers[1]["id"]
    payment_id = next(p["id"] for p in dataset.payments if p["customer_id"] == customer_id)
    campaign, opportunity = _real_campaign_and_opportunity(db_session, dataset, payment_id=payment_id, customer_id=customer_id)

    db_session.add(RecoveryAction(
        campaign_id=campaign.id, opportunity_id=opportunity.id, payment_id=payment_id,
        customer_id=customer_id, action_type=RecommendedAction.PAYMENT_LINK, status=RecoveryActionStatus.EXECUTED,
    ))
    db_session.commit()

    engine = PolicyEngine(db_session)
    result = engine.check_customer_contact_limit(customer_id, _policy(max_customer_contacts=1))
    assert result.passed is False
