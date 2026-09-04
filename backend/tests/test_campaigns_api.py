"""API-level tests for the Phase 4 campaign endpoints."""

from app.services import recovery_predictor


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


def test_create_campaign_endpoint(client, dataset, clean_campaign_state, monkeypatch):
    payment_ids = [dataset.payment_failures[0]["payment_id"], dataset.payment_failures[1]["payment_id"]]
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})

    response = client.post("/api/recovery/campaigns", json={
        "name": "API Test Campaign",
        "payment_ids": [str(pid) for pid in payment_ids],
        "created_by": "api_tester",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["campaign"]["status"] == "PENDING_APPROVAL"
    assert body["campaign"]["target_count"] == 2
    assert body["excluded"] == []


def test_create_campaign_rejects_empty_payment_list(client):
    response = client.post("/api/recovery/campaigns", json={"name": "x", "payment_ids": [], "created_by": "a"})
    assert response.status_code == 422


def test_create_campaign_returns_422_when_nothing_qualifies(client, dataset, clean_campaign_state, monkeypatch):
    payment_ids = [dataset.payment_failures[0]["payment_id"]]
    _patch_predictions(monkeypatch, {pid: _prediction(0.1) for pid in payment_ids})

    response = client.post("/api/recovery/campaigns", json={
        "name": "x", "payment_ids": [str(pid) for pid in payment_ids], "created_by": "a",
    })
    assert response.status_code == 422


def test_full_lifecycle_via_api(client, dataset, clean_campaign_state, monkeypatch):
    payment_ids = [dataset.payment_failures[2]["payment_id"]]
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})

    create_resp = client.post("/api/recovery/campaigns", json={
        "name": "Lifecycle Test", "payment_ids": [str(pid) for pid in payment_ids], "created_by": "a",
    })
    assert create_resp.status_code == 200
    campaign_id = create_resp.json()["campaign"]["id"]

    get_resp = client.get(f"/api/recovery/campaigns/{campaign_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "PENDING_APPROVAL"
    assert len(get_resp.json()["recommendations"]) == 1

    approve_resp = client.post(f"/api/recovery/campaigns/{campaign_id}/approve", json={"approved_by": "owner"})
    assert approve_resp.status_code == 200
    approved_body = approve_resp.json()
    assert approved_body["status"] == "APPROVED"
    assert approved_body["approved_by"] == "owner"
    assert all(a["status"] == "PENDING" for a in approved_body["actions"])

    execute_resp = client.post(f"/api/recovery/campaigns/{campaign_id}/execute")
    assert execute_resp.status_code == 200
    executed_body = execute_resp.json()
    assert executed_body["status"] == "COMPLETED"
    assert all(a["status"] == "EXECUTED" for a in executed_body["actions"])
    assert all(a["provider_response"]["success"] for a in executed_body["actions"])

    list_resp = client.get("/api/recovery/campaigns")
    assert list_resp.status_code == 200
    assert any(c["id"] == campaign_id for c in list_resp.json()["items"])


def test_approve_twice_returns_409(client, dataset, clean_campaign_state, monkeypatch):
    # index 12, not 3: payment_failures[3] is a CARD_LIMIT failure, which
    # the action selector correctly recommends ALTERNATIVE_PAYMENT_METHOD
    # for (not executable) -- this test is about approval idempotency, so
    # it needs a payment whose recommended action is actually executable.
    payment_ids = [dataset.payment_failures[12]["payment_id"]]
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign_id = client.post("/api/recovery/campaigns", json={
        "name": "x", "payment_ids": [str(pid) for pid in payment_ids], "created_by": "a",
    }).json()["campaign"]["id"]

    first = client.post(f"/api/recovery/campaigns/{campaign_id}/approve", json={"approved_by": "owner"})
    assert first.status_code == 200
    second = client.post(f"/api/recovery/campaigns/{campaign_id}/approve", json={"approved_by": "owner"})
    assert second.status_code == 409


def test_execute_before_approval_returns_409(client, dataset, clean_campaign_state, monkeypatch):
    payment_ids = [dataset.payment_failures[6]["payment_id"]]
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign_id = client.post("/api/recovery/campaigns", json={
        "name": "x", "payment_ids": [str(pid) for pid in payment_ids], "created_by": "a",
    }).json()["campaign"]["id"]

    response = client.post(f"/api/recovery/campaigns/{campaign_id}/execute")
    assert response.status_code == 409


def test_execute_twice_returns_409(client, dataset, clean_campaign_state, monkeypatch):
    payment_ids = [dataset.payment_failures[7]["payment_id"]]
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign_id = client.post("/api/recovery/campaigns", json={
        "name": "x", "payment_ids": [str(pid) for pid in payment_ids], "created_by": "a",
    }).json()["campaign"]["id"]

    client.post(f"/api/recovery/campaigns/{campaign_id}/approve", json={"approved_by": "owner"})
    first = client.post(f"/api/recovery/campaigns/{campaign_id}/execute")
    assert first.status_code == 200
    second = client.post(f"/api/recovery/campaigns/{campaign_id}/execute")
    assert second.status_code == 409


def test_execute_nonexistent_campaign_404(client):
    import uuid
    response = client.post(f"/api/recovery/campaigns/{uuid.uuid4()}/execute")
    assert response.status_code == 404


def test_campaign_detail_audit_trail_shows_full_timeline(client, dataset, clean_campaign_state, monkeypatch):
    payment_ids = [dataset.payment_failures[8]["payment_id"]]
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})

    campaign_id = client.post("/api/recovery/campaigns", json={
        "name": "Audit Trail Test", "payment_ids": [str(pid) for pid in payment_ids], "created_by": "a",
    }).json()["campaign"]["id"]
    client.post(f"/api/recovery/campaigns/{campaign_id}/approve", json={"approved_by": "owner"})
    detail = client.post(f"/api/recovery/campaigns/{campaign_id}/execute").json()

    event_types = [entry["event_type"] for entry in detail["audit_trail"]]
    assert "campaign_created" in event_types
    assert "policy_checked" in event_types
    assert "campaign_approved" in event_types
    assert "recovery_action_authorized" in event_types
    assert "recovery_action_executed" in event_types

    # Chronological.
    timestamps = [entry["created_at"] for entry in detail["audit_trail"]]
    assert timestamps == sorted(timestamps)


def test_reject_campaign_via_api(client, dataset, clean_campaign_state, monkeypatch):
    payment_ids = [dataset.payment_failures[4]["payment_id"]]
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign_id = client.post("/api/recovery/campaigns", json={
        "name": "x", "payment_ids": [str(pid) for pid in payment_ids], "created_by": "a",
    }).json()["campaign"]["id"]

    response = client.post(f"/api/recovery/campaigns/{campaign_id}/reject", json={
        "rejected_by": "owner", "reason": "wrong timing",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CANCELLED"
    assert body["rejection_reason"] == "wrong timing"
    assert all(r["status"] == "REJECTED" for r in body["recommendations"])


def test_reject_missing_reason_is_rejected(client, dataset, clean_campaign_state, monkeypatch):
    payment_ids = [dataset.payment_failures[5]["payment_id"]]
    _patch_predictions(monkeypatch, {pid: _prediction(0.9) for pid in payment_ids})
    campaign_id = client.post("/api/recovery/campaigns", json={
        "name": "x", "payment_ids": [str(pid) for pid in payment_ids], "created_by": "a",
    }).json()["campaign"]["id"]

    response = client.post(f"/api/recovery/campaigns/{campaign_id}/reject", json={"rejected_by": "owner", "reason": ""})
    assert response.status_code == 422


def test_get_nonexistent_campaign_404(client):
    import uuid
    response = client.get(f"/api/recovery/campaigns/{uuid.uuid4()}")
    assert response.status_code == 404


def test_approve_nonexistent_campaign_404(client):
    import uuid
    response = client.post(f"/api/recovery/campaigns/{uuid.uuid4()}/approve", json={"approved_by": "owner"})
    assert response.status_code == 404
