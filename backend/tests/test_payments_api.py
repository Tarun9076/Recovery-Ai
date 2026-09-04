def test_list_payments(client, dataset):
    response = client.get("/api/payments", params={"limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(dataset.payments)
    assert len(body["items"]) == 10


def test_list_payments_filter_by_status(client):
    response = client.get("/api/payments", params={"status": "failed", "limit": 500})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert all(item["status"] == "failed" for item in body["items"])


def test_list_failed_payments_includes_failure_detail(client):
    response = client.get("/api/payments/failed", params={"limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    for item in body["items"]:
        assert item["status"] == "failed"
        assert item["failure"] is not None
        assert "failure_category" in item["failure"]
        # Ground truth must never be exposed as a feature.
        assert "eventually_recovered" not in item["failure"]


def test_get_single_payment_not_found(client):
    import uuid

    response = client.get(f"/api/payments/{uuid.uuid4()}")
    assert response.status_code == 404
