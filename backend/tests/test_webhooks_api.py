"""API-level tests for POST /api/webhooks/razorpay."""

import hashlib
import hmac
import json

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

WEBHOOK_SECRET = "api_test_webhook_secret"


def _sign(body: str, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def _seed_executed_action(session, dataset, payment_index=0) -> RecoveryAction:
    payment = dataset.payments[payment_index]
    campaign = RecoveryCampaign(
        merchant_id=dataset.merchant["id"], name="api-fixture", target_count=1,
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
        status=RecoveryActionStatus.EXECUTED, payment_link_id="plink_apitest",
        provider_response={"success": True, "payment_link_id": "plink_apitest", "payment_link": "https://x", "status": "created"},
    )
    session.add(action)
    session.commit()
    session.refresh(action)
    return action


def test_webhook_endpoint_confirms_recovery(client, db_session, dataset, clean_campaign_state, monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    get_settings.cache_clear()
    try:
        action = _seed_executed_action(db_session, dataset)
        body = json.dumps({
            "event": "payment_link.paid",
            "payload": {"payment_link": {"entity": {"id": "plink_apitest", "amount_paid": 250000, "status": "paid"}}},
        })
        response = client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "recovered"

        db_session.refresh(action)
        assert action.status == RecoveryActionStatus.RECOVERED
        assert action.recovered_amount == 2500.0
    finally:
        get_settings.cache_clear()


def test_webhook_endpoint_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    get_settings.cache_clear()
    try:
        body = json.dumps({"event": "payment_link.paid", "payload": {}})
        response = client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": "0" * 64, "Content-Type": "application/json"},
        )
        assert response.status_code == 400
    finally:
        get_settings.cache_clear()


def test_webhook_endpoint_missing_signature_header_is_422(client):
    response = client.post("/api/webhooks/razorpay", content="{}", headers={"Content-Type": "application/json"})
    assert response.status_code == 422
