"""Spec section 9's two named demo scenarios, end to end through the real
API, each asserting the full flow it describes rather than just one field.
"""

from app.services import recovery_predictor
from app.services.payment_provider import PaymentProvider


def _patch_predictions(monkeypatch, mapping: dict):
    def fake_predict_recovery(payment_id, session):
        return mapping[payment_id]
    monkeypatch.setattr(recovery_predictor, "predict_recovery", fake_predict_recovery)


def _prediction(probability=0.9, confidence=0.8, amount=1000.0):
    return {"recovery_probability": probability, "expected_recovery": amount * probability, "confidence": confidence}


class _TimeoutProvider(PaymentProvider):
    """Simulates the provider-timeout scenario: link creation itself never
    succeeds."""

    def create_recovery_link(self, **kwargs):
        raise TimeoutError("simulated provider timeout")


def test_scenario_provider_timeout_then_retry(client, db_session, dataset, clean_campaign_state, monkeypatch):
    """Recovery link created (attempted) -> provider timeout -> action
    marked failed -> no recovered revenue -> merchant can retry."""
    from app.services import campaign_service

    payment_id = dataset.payment_failures[0]["payment_id"]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})

    campaign, _ = campaign_service.create_campaign(
        db_session, name="Timeout Scenario", payment_ids=[payment_id], created_by="tester",
    )
    approved = campaign_service.approve_campaign(
        db_session, campaign.id, approved_by="owner", provider=_TimeoutProvider(),
    )

    # Action marked failed, no recovered revenue.
    assert approved.status.value == "FAILED"
    from sqlmodel import select
    from app.models.recovery_action import RecoveryAction
    action = db_session.exec(select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)).first()
    assert action.status.value == "FAILED"
    assert action.recovered_amount is None
    assert action.provider_response["success"] is False
    assert "timeout" in action.provider_response["error"].lower()

    from app.services.metrics_service import compute_campaign_metrics
    metrics = compute_campaign_metrics(db_session, campaign)
    assert metrics.revenue_recovered == 0.0

    # Merchant can retry: a new campaign for the same payment must now be allowed.
    retry_campaign, excluded = campaign_service.create_campaign(
        db_session, name="Retry After Timeout", payment_ids=[payment_id], created_by="tester",
    )
    assert retry_campaign.target_count == 1
    assert excluded == []

    # This time it succeeds with the real (mock) provider.
    retried = campaign_service.approve_campaign(db_session, retry_campaign.id, approved_by="owner")
    assert retried.status.value == "COMPLETED"


def test_scenario_customer_does_not_pay(client, db_session, dataset, clean_campaign_state, monkeypatch):
    """Recovery link created -> customer does not pay -> status remains
    pending (EXECUTED, not RECOVERED/FAILED) -> recovered revenue = ₹0."""
    from app.services import campaign_service
    from app.services.metrics_service import compute_campaign_metrics

    payment_id = dataset.payment_failures[1]["payment_id"]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})

    campaign, _ = campaign_service.create_campaign(
        db_session, name="No Payment Scenario", payment_ids=[payment_id], created_by="tester",
    )
    approved = campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner")
    assert approved.status.value == "COMPLETED"  # the *link* was created successfully

    from sqlmodel import select
    from app.models.recovery_action import RecoveryAction
    from app.models.recovery_opportunity import RecoveryOpportunity

    action = db_session.exec(select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)).first()
    assert action.status.value == "EXECUTED"  # neither RECOVERED nor FAILED -- genuinely pending
    assert action.recovered_amount is None
    assert action.recovered_at is None

    opportunity = db_session.get(RecoveryOpportunity, action.opportunity_id)
    assert opportunity.status.value == "EXECUTED"

    metrics = compute_campaign_metrics(db_session, campaign)
    assert metrics.revenue_recovered == 0.0
    assert metrics.recovery_rate == 0.0

    # No webhook, no simulation -- confirmed via the real API too.
    detail = client.get(f"/api/recovery/campaigns/{campaign.id}").json()
    assert detail["revenue_recovered"] == 0.0
    assert detail["actions"][0]["status"] == "EXECUTED"
