"""API-level tests for POST /api/mock/simulate-payment."""

import uuid

from app.services import recovery_predictor


def _patch_predictions(monkeypatch, mapping: dict):
    def fake_predict_recovery(payment_id, session):
        return mapping[payment_id]
    monkeypatch.setattr(recovery_predictor, "predict_recovery", fake_predict_recovery)


def _prediction(probability=0.9, confidence=0.8, amount=1000.0):
    return {"recovery_probability": probability, "expected_recovery": amount * probability, "confidence": confidence}


def test_simulate_payment_endpoint_full_flow(client, dataset, clean_campaign_state, monkeypatch):
    payment_id = dataset.payment_failures[0]["payment_id"]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})

    create_resp = client.post("/api/recovery/campaigns", json={
        "name": "Mock API Test", "payment_ids": [str(payment_id)], "created_by": "tester",
    })
    campaign_id = create_resp.json()["campaign"]["id"]
    client.post(f"/api/recovery/campaigns/{campaign_id}/approve", json={"approved_by": "owner"})
    execute_resp = client.post(f"/api/recovery/campaigns/{campaign_id}/execute")
    action_id = execute_resp.json()["actions"][0]["id"]

    sim_resp = client.post("/api/mock/simulate-payment", json={"recovery_action_id": action_id})
    assert sim_resp.status_code == 200
    body = sim_resp.json()
    assert body["simulated"] is True
    assert body["status"] == "recovered"

    detail = client.get(f"/api/recovery/campaigns/{campaign_id}").json()
    assert detail["revenue_recovered"] > 0
    assert detail["actions"][0]["status"] == "RECOVERED"


def test_simulate_payment_endpoint_unknown_action_404(client):
    response = client.post("/api/mock/simulate-payment", json={"recovery_action_id": str(uuid.uuid4())})
    assert response.status_code == 404


def test_simulate_payment_endpoint_blocked_outside_mock_mode(client, dataset, clean_campaign_state, monkeypatch):
    from app.core.config import get_settings

    payment_id = dataset.payment_failures[1]["payment_id"]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})
    create_resp = client.post("/api/recovery/campaigns", json={
        "name": "Mock Blocked Test", "payment_ids": [str(payment_id)], "created_by": "tester",
    })
    campaign_id = create_resp.json()["campaign"]["id"]
    approve_resp = client.post(f"/api/recovery/campaigns/{campaign_id}/approve", json={"approved_by": "owner"})
    action_id = approve_resp.json()["actions"][0]["id"]

    monkeypatch.setenv("RAZORPAY_MODE", "test")
    get_settings.cache_clear()
    try:
        response = client.post("/api/mock/simulate-payment", json={"recovery_action_id": action_id})
        assert response.status_code == 403
    finally:
        get_settings.cache_clear()
