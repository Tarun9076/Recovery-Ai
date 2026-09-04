"""Tests for metrics_service.py (spec section 7)."""

import pytest

from app.services import campaign_service, recovery_predictor
from app.services.metrics_service import RecoveryMetrics, compute_campaign_metrics, compute_portfolio_metrics
from app.services.mock_service import simulate_payment


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


def test_recovery_rate_is_zero_with_no_recoverable_revenue():
    metrics = RecoveryMetrics(revenue_at_risk=1000.0, recoverable_revenue=0.0, revenue_recovered=0.0)
    assert metrics.recovery_rate == 0.0


def test_recovery_rate_formula():
    """Recovery Rate = Actual Revenue Recovered / Recoverable Revenue (spec section 7)."""
    metrics = RecoveryMetrics(revenue_at_risk=1000.0, recoverable_revenue=800.0, revenue_recovered=400.0)
    assert metrics.recovery_rate == pytest.approx(0.5)


def test_campaign_metrics_before_any_recovery(db_session, dataset, clean_campaign_state, monkeypatch):
    payment_id = dataset.payment_failures[0]["payment_id"]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})
    campaign, _ = campaign_service.create_campaign(
        db_session, name="Metrics Test", payment_ids=[payment_id], created_by="tester",
    )
    campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner")

    metrics = compute_campaign_metrics(db_session, campaign)
    assert metrics.revenue_at_risk == campaign.total_amount
    assert metrics.recoverable_revenue == campaign.expected_recovery
    assert metrics.revenue_recovered == 0.0
    assert metrics.recovery_rate == 0.0


def test_campaign_metrics_after_recovery(db_session, dataset, clean_campaign_state, monkeypatch):
    payment_id = dataset.payment_failures[1]["payment_id"]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})
    campaign, _ = campaign_service.create_campaign(
        db_session, name="Metrics Test 2", payment_ids=[payment_id], created_by="tester",
    )
    campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner")

    from sqlmodel import select
    from app.models.recovery_action import RecoveryAction
    action = db_session.exec(select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)).first()

    simulate_payment(db_session, action.id)

    metrics = compute_campaign_metrics(db_session, campaign)
    assert metrics.revenue_recovered > 0.0
    assert metrics.recovery_rate > 0.0
    # Never derived from expected_recovery: simulate_payment defaults to
    # the full payment amount, so revenue_recovered lands at revenue_at_risk
    # (the raw payment amount), not recoverable_revenue (amount * 0.9 probability).
    assert metrics.revenue_recovered == pytest.approx(metrics.revenue_at_risk)
    assert metrics.revenue_recovered != pytest.approx(metrics.recoverable_revenue)


def test_portfolio_metrics_reflect_only_verified_recoveries(db_session, dataset, clean_campaign_state, monkeypatch):
    before = compute_portfolio_metrics(db_session)

    payment_id = dataset.payment_failures[2]["payment_id"]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})
    campaign, _ = campaign_service.create_campaign(
        db_session, name="Portfolio Test", payment_ids=[payment_id], created_by="tester",
    )
    campaign_service.approve_campaign(db_session, campaign.id, approved_by="owner")

    # Approving alone (no webhook) must not move revenue_recovered.
    mid = compute_portfolio_metrics(db_session)
    assert mid.revenue_recovered == before.revenue_recovered

    from sqlmodel import select
    from app.models.recovery_action import RecoveryAction
    action = db_session.exec(select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)).first()
    simulate_payment(db_session, action.id)

    after = compute_portfolio_metrics(db_session)
    assert after.revenue_recovered > mid.revenue_recovered
