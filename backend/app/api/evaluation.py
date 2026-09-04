from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import get_session
from app.schemas.evaluation import BaselineComparisonRead, BusinessMetricsRead, ModelEvaluationRead
from app.services.evaluation_service import ModelNotEvaluatedError, load_model_evaluation
from app.services.metrics_service import compute_baseline_comparison, compute_portfolio_metrics

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/model", response_model=ModelEvaluationRead)
def get_model_evaluation() -> ModelEvaluationRead:
    """Precision/Recall/F1/ROC-AUC/PR-AUC/Brier/FP-cost/FN-cost (spec
    section 1) -- all read fresh from `ml/models/recovery_model_meta.json`,
    the file `ml/training/train.py` writes after actually scoring the
    model against its held-out temporal test split. Re-train and this
    endpoint's numbers change; nothing here is hardcoded."""
    try:
        return ModelEvaluationRead(**load_model_evaluation())
    except ModelNotEvaluatedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/business", response_model=BusinessMetricsRead)
def get_business_metrics(session: Session = Depends(get_session)) -> BusinessMetricsRead:
    """Failed transaction value / revenue at risk / predicted recoverable
    revenue / actual recovered revenue / recovery rate (spec section 1),
    computed fresh from the database -- see
    `metrics_service.compute_portfolio_metrics`."""
    metrics = compute_portfolio_metrics(session)
    return BusinessMetricsRead(
        failed_transaction_value=metrics.revenue_at_risk,
        revenue_at_risk=metrics.revenue_at_risk,
        predicted_recoverable_revenue=metrics.recoverable_revenue,
        actual_recovered_revenue=metrics.revenue_recovered,
        recovery_rate=metrics.recovery_rate,
    )


@router.get("/baseline-comparison", response_model=BaselineComparisonRead)
def get_baseline_comparison(session: Session = Depends(get_session)) -> BaselineComparisonRead:
    """Baseline (no AI intervention) vs RecoverAI (spec section 1) -- see
    `metrics_service.compute_baseline_comparison` for what "baseline"
    means and why it never exposes ground truth per-payment."""
    comparison = compute_baseline_comparison(session)
    return BaselineComparisonRead(**comparison.as_dict())
