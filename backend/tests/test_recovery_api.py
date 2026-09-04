"""API-level tests for the Phase 2 recovery endpoints."""


def test_analyze_endpoint(client, dataset):
    response = client.post("/api/recovery/analyze")
    assert response.status_code == 200
    body = response.json()

    assert body["analyzed_count"] == len(dataset.payment_failures)
    assert (
        body["high_recovery_count"] + body["medium_recovery_count"] + body["low_recovery_count"]
        == body["analyzed_count"]
    )
    assert body["model_name"]
    assert body["model_version"]
    assert body["feature_version"]
    assert body["training_timestamp"] is not None


def test_opportunities_are_ranked_by_expected_recovery_desc(client, dataset):
    client.post("/api/recovery/analyze")

    response = client.get("/api/recovery/opportunities", params={"limit": 100})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(dataset.payment_failures)

    expected_recoveries = [item["expected_recovery"] for item in body["items"]]
    assert expected_recoveries == sorted(expected_recoveries, reverse=True)

    # Ranking must not just be transaction amount -- a smaller amount with a
    # much higher probability can outrank a larger amount with a low one.
    amounts = [item["amount"] for item in body["items"]]
    assert amounts != sorted(amounts, reverse=True), (
        "ranking looks identical to sorting by amount -- expected_recovery isn't doing anything"
    )


def test_opportunities_filter_by_segment(client, dataset):
    client.post("/api/recovery/analyze")

    response = client.get("/api/recovery/opportunities", params={"segment": "HIGH_RECOVERY", "limit": 500})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert all(item["segment"] == "HIGH_RECOVERY" for item in body["items"])


def test_opportunity_detail_matches_spec_shape(client, dataset):
    client.post("/api/recovery/analyze")
    payment_id = dataset.payment_failures[0]["payment_id"]

    response = client.get(f"/api/recovery/opportunities/{payment_id}")
    assert response.status_code == 200
    body = response.json()

    assert body["payment_id"] == str(payment_id)
    assert 0.0 <= body["recovery_probability"] <= 1.0
    assert body["expected_recovery"] >= 0
    assert 0.0 <= body["confidence"] <= 1.0
    assert isinstance(body["top_factors"], list)
    assert body["model_name"] and body["model_version"] and body["feature_version"]


def test_opportunity_detail_computes_on_demand_when_not_yet_analyzed(client, dataset):
    """No POST /analyze called first -- the detail endpoint should still
    work by computing (and persisting) the prediction on the fly."""
    payment_id = dataset.payment_failures[-1]["payment_id"]
    response = client.get(f"/api/recovery/opportunities/{payment_id}")
    assert response.status_code == 200
    assert response.json()["payment_id"] == str(payment_id)


def test_opportunity_detail_404_for_non_failed_payment(client, dataset):
    import uuid

    successful_payment = next(p for p in dataset.payments if p["status"] != "failed")
    response = client.get(f"/api/recovery/opportunities/{successful_payment['id']}")
    assert response.status_code == 404

    response = client.get(f"/api/recovery/opportunities/{uuid.uuid4()}")
    assert response.status_code == 404


def test_ground_truth_never_exposed_via_api(client, dataset):
    client.post("/api/recovery/analyze")
    response = client.get("/api/recovery/opportunities", params={"limit": 50})
    body_text = response.text
    assert "eventually_recovered" not in body_text
    assert "recoverability" not in body_text
