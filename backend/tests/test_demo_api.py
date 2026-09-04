"""API-level tests for the Phase 8 /api/demo/* endpoints."""

from app.services import recovery_predictor


def _patch_predictions(monkeypatch, mapping: dict):
    def fake_predict_recovery(payment_id, session):
        return mapping[payment_id]
    monkeypatch.setattr(recovery_predictor, "predict_recovery", fake_predict_recovery)


def _prediction(probability=0.9, confidence=0.8, amount=1000.0):
    return {"recovery_probability": probability, "expected_recovery": amount * probability, "confidence": confidence}


def test_reset_demo_clears_workflow_tables_but_keeps_the_dataset(client, dataset, clean_campaign_state, monkeypatch):
    payment_ids = [dataset.payment_failures[0]["payment_id"]]
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})

    campaign_id = client.post("/api/recovery/campaigns", json={
        "name": "x", "payment_ids": [str(pid) for pid in payment_ids], "created_by": "a",
    }).json()["campaign"]["id"]
    client.post(f"/api/recovery/campaigns/{campaign_id}/approve", json={"approved_by": "owner"})

    failed_before = client.get("/api/payments/failed", params={"limit": 1}).json()["total"]

    reset_resp = client.post("/api/demo/reset")
    assert reset_resp.status_code == 200
    counts = reset_resp.json()
    assert counts["recovery_campaigns"] >= 1
    assert counts["recovery_actions"] >= 1

    list_resp = client.get("/api/recovery/campaigns")
    assert list_resp.json()["total"] == 0

    failed_after = client.get("/api/payments/failed", params={"limit": 1}).json()["total"]
    assert failed_after == failed_before


def test_simulate_provider_failure_records_a_failed_action_with_no_recovered_revenue(
    client, dataset, clean_campaign_state, monkeypatch,
):
    payment_id = dataset.payment_failures[1]["payment_id"]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})

    response = client.post("/api/demo/simulate-provider-failure", json={"payment_id": str(payment_id)})
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "FAILED"
    assert len(body["actions"]) == 1
    action = body["actions"][0]
    assert action["status"] == "FAILED"
    assert action["provider_response"]["success"] is False
    assert body["revenue_recovered"] == 0.0


def test_payment_stays_retryable_after_a_simulated_provider_failure(
    client, dataset, clean_campaign_state, monkeypatch,
):
    payment_id = dataset.payment_failures[2]["payment_id"]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})

    first = client.post("/api/demo/simulate-provider-failure", json={"payment_id": str(payment_id)})
    assert first.status_code == 200

    retry_resp = client.post("/api/recovery/campaigns", json={
        "name": "Retry", "payment_ids": [str(payment_id)], "created_by": "a",
    })
    assert retry_resp.status_code == 200
    assert retry_resp.json()["excluded"] == []


def test_simulate_provider_failure_blocked_outside_mock_mode(client, dataset, clean_campaign_state, monkeypatch):
    from app.core.config import get_settings

    payment_id = dataset.payment_failures[3]["payment_id"]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.9)})

    monkeypatch.setenv("RAZORPAY_MODE", "test")
    get_settings.cache_clear()
    try:
        response = client.post("/api/demo/simulate-provider-failure", json={"payment_id": str(payment_id)})
        assert response.status_code == 403
    finally:
        get_settings.cache_clear()


def test_simulate_provider_failure_422_when_no_candidate_qualifies(client, dataset, clean_campaign_state, monkeypatch):
    payment_id = dataset.payment_failures[4]["payment_id"]
    _patch_predictions(monkeypatch, {payment_id: _prediction(0.05)})  # below policy threshold

    response = client.post("/api/demo/simulate-provider-failure", json={"payment_id": str(payment_id)})
    assert response.status_code == 422
