"""Tests for the `webhook_events` table and event-id-based idempotency
(spec sections 3-4) -- distinct from test_webhook_service.py's tests of the
recovery-matching business logic itself."""

import hashlib
import hmac
import json

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
from app.models.webhook_event import WebhookEvent
from app.services.webhook_service import process_razorpay_webhook

WEBHOOK_SECRET = "events_test_secret"


def _sign(body: str, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def _seed_executed_action(session, dataset, payment_index=0) -> RecoveryAction:
    payment = dataset.payments[payment_index]
    campaign = RecoveryCampaign(
        merchant_id=dataset.merchant["id"], name="events-fixture", target_count=1,
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
        status=RecoveryActionStatus.EXECUTED, payment_link_id=f"plink_events_{payment_index}",
        provider_response={"success": True, "payment_link_id": f"plink_events_{payment_index}", "payment_link": "https://x", "status": "created"},
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


def test_valid_webhook_is_stored_verified_and_processed(db_session, dataset, clean_campaign_state, webhook_secret_configured):
    action = _seed_executed_action(db_session, dataset)
    body = json.dumps({
        "event": "payment_link.paid",
        "payload": {"payment_link": {"entity": {"id": "plink_events_0", "amount_paid": 100000, "status": "paid"}}},
    })
    process_razorpay_webhook(db_session, body, _sign(body), event_id="evt_stored_001")

    events = db_session.exec(select(WebhookEvent).where(WebhookEvent.event_id == "evt_stored_001")).all()
    assert len(events) == 1
    event = events[0]
    assert event.provider == "razorpay"
    assert event.event_type == "payment_link.paid"
    assert event.signature_verified is True
    assert event.processed is True
    assert event.processed_at is not None
    assert event.payload["event"] == "payment_link.paid"


def test_invalid_signature_is_stored_unverified_and_unprocessed(db_session, webhook_secret_configured):
    from app.integrations.razorpay.exceptions import RazorpayWebhookSignatureError

    body = json.dumps({"event": "payment_link.paid"})
    with pytest.raises(RazorpayWebhookSignatureError):
        process_razorpay_webhook(db_session, body, "0" * 64, event_id="evt_bad_sig_002")

    event = db_session.exec(select(WebhookEvent).where(WebhookEvent.event_id == "evt_bad_sig_002")).first()
    assert event is not None
    assert event.signature_verified is False
    assert event.processed is False
    assert event.processed_at is None


def test_same_event_id_redelivered_is_not_reprocessed(db_session, dataset, clean_campaign_state, webhook_secret_configured):
    action = _seed_executed_action(db_session, dataset)
    body = json.dumps({
        "event": "payment_link.paid",
        "payload": {"payment_link": {"entity": {"id": "plink_events_0", "amount_paid": 500000, "status": "paid"}}},
    })
    sig = _sign(body)

    first = process_razorpay_webhook(db_session, body, sig, event_id="evt_redeliver_003")
    assert first["status"] == "recovered"

    second = process_razorpay_webhook(db_session, body, sig, event_id="evt_redeliver_003")
    assert second["status"] == "already_recorded"
    assert second["webhook_event_id"] == first["webhook_event_id"]

    # Exactly one row for this event id -- the unique constraint, not just app logic.
    rows = db_session.exec(select(WebhookEvent).where(WebhookEvent.event_id == "evt_redeliver_003")).all()
    assert len(rows) == 1

    db_session.refresh(action)
    assert action.recovered_amount == 5000.0  # not double-applied


def test_missing_event_id_falls_back_to_content_hash(db_session, dataset, clean_campaign_state, webhook_secret_configured):
    """No x-razorpay-event-id header (event_id=None) -- an exact-duplicate
    request must still dedup via the body+signature hash fallback."""
    action = _seed_executed_action(db_session, dataset)
    body = json.dumps({
        "event": "payment_link.paid",
        "payload": {"payment_link": {"entity": {"id": "plink_events_0", "amount_paid": 200000, "status": "paid"}}},
    })
    sig = _sign(body)

    first = process_razorpay_webhook(db_session, body, sig, event_id=None)
    assert first["status"] == "recovered"

    second = process_razorpay_webhook(db_session, body, sig, event_id=None)
    assert second["status"] == "already_recorded"

    db_session.refresh(action)
    assert action.recovered_amount == 2000.0


def test_different_events_get_different_stored_rows(db_session, dataset, clean_campaign_state, webhook_secret_configured):
    _seed_executed_action(db_session, dataset, payment_index=0)
    body1 = json.dumps({"event": "payment.failed", "payload": {}})
    body2 = json.dumps({"event": "payment.failed", "payload": {}, "note": "different"})

    process_razorpay_webhook(db_session, body1, _sign(body1), event_id="evt_a")
    process_razorpay_webhook(db_session, body2, _sign(body2), event_id="evt_b")

    rows = db_session.exec(select(WebhookEvent).where(WebhookEvent.event_id.in_(["evt_a", "evt_b"]))).all()
    assert len(rows) == 2
    assert {r.event_type for r in rows} == {"payment.failed"}
    assert all(r.processed for r in rows)  # ignored events are still marked processed -- nothing more to do
