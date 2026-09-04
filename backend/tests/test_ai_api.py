"""API-level tests for POST /api/ai/investigate. Uses the `client` fixture,
which overrides the LLM client to MockLLMClient (see conftest.py) -- fast,
deterministic, no network dependency."""

from sqlmodel import select

from app.models.ai_investigation import AIInvestigation


def test_investigate_endpoint_returns_valid_shape(client, dataset):
    response = client.post("/api/ai/investigate", json={"question": "Why did revenue drop?"})
    assert response.status_code == 200
    body = response.json()

    assert isinstance(body["summary"], str) and body["summary"]
    assert isinstance(body["findings"], list)
    assert isinstance(body["recommendations"], list)
    assert body["revenue_at_risk"] >= 0
    assert body["recoverable_revenue"] >= 0

    for finding in body["findings"]:
        assert finding["severity"] in {"low", "medium", "high"}
        assert finding["affected_payment_count"] >= 0

    for rec in body["recommendations"]:
        assert rec["recommended_action"] in {
            "PAYMENT_LINK", "RETRY", "ALTERNATIVE_PAYMENT_METHOD", "REMINDER", "NO_ACTION", "MANUAL_REVIEW",
        }
        assert 0.0 <= rec["confidence"] <= 1.0


def test_investigate_endpoint_rejects_empty_question(client):
    response = client.post("/api/ai/investigate", json={"question": ""})
    assert response.status_code == 422


def test_investigate_endpoint_writes_audit_record(client, db_session, dataset):
    before = db_session.exec(select(AIInvestigation)).all()

    response = client.post("/api/ai/investigate", json={"question": "Why did revenue drop?"})
    assert response.status_code == 200
    body = response.json()

    after = db_session.exec(select(AIInvestigation)).all()
    assert len(after) == len(before) + 1

    record = sorted(after, key=lambda r: r.created_at)[-1]
    assert record.question == "Why did revenue drop?"
    assert "get_failure_statistics" in record.tools_used
    assert "analyze_failure_spike" in record.tools_used
    assert record.revenue_at_risk == body["revenue_at_risk"]
    assert record.recoverable_revenue == body["recoverable_revenue"]
    assert set(record.data_sources) == {"payments", "payment_failures", "customers", "recovery_predictions", "merchant_policies"}


def test_investigate_endpoint_never_returns_ground_truth_fields(client, dataset):
    response = client.post("/api/ai/investigate", json={"question": "Why did revenue drop?"})
    body_text = response.text
    assert "eventually_recovered" not in body_text


def test_list_investigations_includes_a_just_created_one(client, dataset):
    create_resp = client.post("/api/ai/investigate", json={"question": "List-investigations test question?"})
    assert create_resp.status_code == 200

    list_resp = client.get("/api/ai/investigations", params={"limit": 5})
    assert list_resp.status_code == 200
    body = list_resp.json()

    assert body["total"] >= 1
    assert len(body["items"]) <= 5
    assert any(item["question"] == "List-investigations test question?" for item in body["items"])
    newest = body["items"][0]
    assert "summary" in newest and "findings" in newest and "recommendations" in newest
    assert "eventually_recovered" not in list_resp.text
