"""Tests for webhook_service.py -- the only code path allowed to mark a
RecoveryAction/RecoveryOpportunity RECOVERED (spec section 11)."""

import hashlib
import hmac
import json
import uuid

import pytest
from sqlmodel import select

from app.core.config import get_settings
from app.integrations.razorpay.exceptions import RazorpayAuthenticationError, RazorpayWebhookSignatureError
from app.models.enums import (
    CampaignStatus,
    OpportunityStatus,
    RecommendedAction,
    RecoveryActionStatus,
)
from app.models.recovery_action import RecoveryAction
from app.models.recovery_campaign import RecoveryCampaign
from app.models.recovery_opportunity import RecoveryOpportunity
from app.services.webhook_service import process_razorpay_webhook

WEBHOOK_SECRET = "test_webhook_secret"


def _sign(body: str, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def _payment_link_paid_body(payment_link_id: str, amount_paid_paise: int = 100000) -> str:
    return json.dumps({
        "entity": "event", "event": "payment_link.paid", "contains": ["payment_link"],
        "payload": {"payment_link": {"entity": {"id": payment_link_id, "amount_paid": amount_paid_paise, "status": "paid"}}},
        "created_at": 1234567890,
    })


def _seed_executed_action(session, dataset) -> RecoveryAction:
    payment = dataset.payments[0]
    campaign = RecoveryCampaign(
        merchant_id=dataset.merchant["id"], name="webhook-fixture", target_count=1,
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
        status=RecoveryActionStatus.EXECUTED, payment_link_id="plink_webhooktest",
        provider_response={"success": True, "payment_link_id": "plink_webhooktest", "payment_link": "https://x", "status": "created"},
    )
    session.add(action)
    session.commit()
    session.refresh(action)
    return action


@pytest.fixture()
def webhook_secret_configured(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_process_webhook_confirms_recovery(db_session, dataset, clean_campaign_state, webhook_secret_configured):
    action = _seed_executed_action(db_session, dataset)
    body = _payment_link_paid_body("plink_webhooktest", amount_paid_paise=150000)

    result = process_razorpay_webhook(db_session, body, _sign(body))

    assert result["status"] == "recovered"
    assert result["amount_paid"] == 1500.0

    db_session.refresh(action)
    assert action.status == RecoveryActionStatus.RECOVERED
    assert action.recovered_amount == 1500.0
    assert action.recovered_at is not None

    opportunity = db_session.get(RecoveryOpportunity, action.opportunity_id)
    assert opportunity.status == OpportunityStatus.RECOVERED


def test_process_webhook_rejects_bad_signature(db_session, dataset, clean_campaign_state, webhook_secret_configured):
    body = _payment_link_paid_body("plink_whatever")
    with pytest.raises(RazorpayWebhookSignatureError):
        process_razorpay_webhook(db_session, body, "0" * 64)


def test_process_webhook_requires_configured_secret(db_session, monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(RazorpayAuthenticationError):
            process_razorpay_webhook(db_session, "{}", "somesig")
    finally:
        get_settings.cache_clear()


def test_process_webhook_ignores_other_events(db_session, dataset, clean_campaign_state, webhook_secret_configured):
    body = json.dumps({"event": "payment.failed", "payload": {}})
    result = process_razorpay_webhook(db_session, body, _sign(body))
    assert result["status"] == "ignored"


def test_process_webhook_ignores_unknown_payment_link(db_session, dataset, clean_campaign_state, webhook_secret_configured):
    body = _payment_link_paid_body("plink_does_not_exist")
    result = process_razorpay_webhook(db_session, body, _sign(body))
    assert result["status"] == "ignored"


def test_process_webhook_is_idempotent_on_redelivery(db_session, dataset, clean_campaign_state, webhook_secret_configured):
    action = _seed_executed_action(db_session, dataset)
    body = _payment_link_paid_body("plink_webhooktest", amount_paid_paise=100000)

    first = process_razorpay_webhook(db_session, body, _sign(body))
    assert first["status"] == "recovered"

    second = process_razorpay_webhook(db_session, body, _sign(body))
    assert second["status"] == "already_recorded"

    db_session.refresh(action)
    assert action.recovered_amount == 1000.0  # unchanged -- not double-applied
