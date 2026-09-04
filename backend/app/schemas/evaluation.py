from datetime import datetime

from pydantic import BaseModel


class CalibrationBin(BaseModel):
    mean_predicted: float
    actual_rate: float
    count: int


class ModelEvaluationRead(BaseModel):
    """Everything here comes straight from `ml/models/recovery_model_meta.json`
    -- the record of the model's own held-out temporal test-set evaluation
    (see `ml/evaluation/evaluate.py`), not a number computed by this API."""

    model_name: str
    model_version: str
    feature_version: str
    algorithm: str
    training_timestamp: datetime
    decision_threshold: float
    dataset_size: int | None = None
    positive_rate: float | None = None

    precision: float
    recall: float
    f1: float
    roc_auc: float
    pr_auc: float
    brier_score: float
    false_positive_count: int
    false_negative_count: int
    true_positive_count: int
    true_negative_count: int
    false_positive_revenue_cost: float
    false_negative_revenue_cost: float

    test_predicted_recoverable_revenue: float
    test_actual_recovered_revenue: float
    test_prediction_error: float
    test_prediction_error_pct: float
    calibration_bins: list[CalibrationBin] = []

    model_config = {"protected_namespaces": ()}


class BusinessMetricsRead(BaseModel):
    """Live business metrics (spec section 1), computed fresh from the
    database on every request -- see `metrics_service.compute_portfolio_metrics`.
    `failed_transaction_value` and `revenue_at_risk` are currently the same
    number (no payment is ever removed from the "failed" population once
    recovered -- see `webhook_service.py`) exposed under both of the
    spec's requested names."""

    failed_transaction_value: float
    revenue_at_risk: float
    predicted_recoverable_revenue: float
    actual_recovered_revenue: float
    recovery_rate: float


class BaselineComparisonRead(BaseModel):
    """Spec section 1: "Baseline vs RecoverAI comparison using actual
    simulation results" -- see `metrics_service.compute_baseline_comparison`
    for exactly what "baseline" means, why it's scoped to only the
    payments RecoverAI actually targeted, and how it's computed."""

    targeted_transaction_value: float
    targeted_payment_count: int
    baseline_recovered_revenue: float
    recoverai_recovered_revenue: float
    incremental_recovered_revenue: float
    baseline_recovery_rate: float
    recoverai_recovery_rate: float
