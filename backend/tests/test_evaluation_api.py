"""API-level tests for the Phase 8 /api/evaluation/* endpoints."""

import json

from app.services.recovery_predictor import META_PATH


def test_get_model_evaluation_matches_the_real_training_artifact(client):
    """Every number in the response must trace back to
    ml/models/recovery_model_meta.json -- the file the actual training run
    wrote -- not to anything hand-typed into the API layer."""
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    classification = meta["test_classification_metrics"]
    business = meta["test_business_metrics"]

    response = client.get("/api/evaluation/model")
    assert response.status_code == 200
    body = response.json()

    assert body["model_name"] == meta["model_name"]
    assert body["algorithm"] == meta["algorithm"]
    assert body["decision_threshold"] == meta["decision_threshold"]
    assert body["precision"] == classification["precision"]
    assert body["recall"] == classification["recall"]
    assert body["f1"] == classification["f1"]
    assert body["roc_auc"] == classification["roc_auc"]
    assert body["pr_auc"] == classification["pr_auc"]
    assert body["brier_score"] == classification["brier_score"]
    assert body["false_positive_revenue_cost"] == classification["false_positive_revenue_cost"]
    assert body["false_negative_revenue_cost"] == classification["false_negative_revenue_cost"]
    assert body["test_predicted_recoverable_revenue"] == business["predicted_recoverable_revenue"]
    assert body["test_actual_recovered_revenue"] == business["actual_recovered_revenue"]

    for metric in ("precision", "recall", "f1", "roc_auc", "pr_auc", "brier_score"):
        assert 0.0 <= body[metric] <= 1.0


def test_get_model_evaluation_503_when_model_missing(client, monkeypatch):
    from app.services import evaluation_service
    from pathlib import Path

    monkeypatch.setattr(evaluation_service, "META_PATH", Path("/nonexistent/meta.json"))
    response = client.get("/api/evaluation/model")
    assert response.status_code == 503


def test_get_business_metrics(client):
    response = client.get("/api/evaluation/business")
    assert response.status_code == 200
    body = response.json()

    assert body["failed_transaction_value"] == body["revenue_at_risk"]
    assert body["failed_transaction_value"] >= 0
    assert body["predicted_recoverable_revenue"] >= 0
    assert body["actual_recovered_revenue"] >= 0
    assert 0.0 <= body["recovery_rate"] <= 1.0
    # Never leaks the ground-truth training label into a live API response.
    assert "eventually_recovered" not in response.text


def test_get_baseline_comparison_with_no_targeted_payments_is_all_zero(client, clean_campaign_state):
    response = client.get("/api/evaluation/baseline-comparison")
    assert response.status_code == 200
    body = response.json()

    assert body["targeted_payment_count"] == 0
    assert body["targeted_transaction_value"] == 0.0
    assert body["baseline_recovered_revenue"] == 0.0
    assert body["recoverai_recovered_revenue"] == 0.0
    assert "eventually_recovered" not in response.text


def test_get_baseline_comparison_scopes_to_targeted_payments_only(client, dataset, clean_campaign_state, monkeypatch):
    from app.services import recovery_predictor

    payment_id = dataset.payment_failures[0]["payment_id"]

    def fake_predict_recovery(pid, session):
        return {"recovery_probability": 0.9, "expected_recovery": 900.0, "confidence": 0.8}
    monkeypatch.setattr(recovery_predictor, "predict_recovery", fake_predict_recovery)

    client.post("/api/recovery/campaigns", json={
        "name": "x", "payment_ids": [str(payment_id)], "created_by": "a",
    })

    response = client.get("/api/evaluation/baseline-comparison")
    assert response.status_code == 200
    body = response.json()

    assert body["targeted_payment_count"] == 1
    assert body["targeted_transaction_value"] > 0
    assert 0 <= body["baseline_recovered_revenue"] <= body["targeted_transaction_value"]
    assert body["incremental_recovered_revenue"] == round(
        body["recoverai_recovered_revenue"] - body["baseline_recovered_revenue"], 2
    )
    assert "eventually_recovered" not in response.text
