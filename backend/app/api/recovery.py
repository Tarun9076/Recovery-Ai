import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models.enums import RecoverySegment
from app.models.merchant_policy import MerchantPolicy
from app.models.payment import Payment
from app.models.payment_failure import PaymentFailure
from app.models.recovery_prediction import RecoveryPrediction
from app.schemas.recovery import (
    AnalyzeResponse,
    PaginatedRecoveryOpportunities,
    RecoveryMetricsRead,
    RecoveryOpportunityRead,
    RecoveryPredictionRead,
)
from app.services.action_selector import RecoveryActionSelector, compute_category_spike_map
from app.services.metrics_service import compute_portfolio_metrics
from app.services.recovery_predictor import (
    ModelNotTrainedError,
    PaymentNotEligibleError,
    analyze_all_failed_payments,
    predict_recovery,
)

router = APIRouter(prefix="/api/recovery", tags=["recovery"])


def _opportunity_query():
    return (
        select(RecoveryPrediction, Payment, PaymentFailure)
        .join(Payment, Payment.id == RecoveryPrediction.payment_id)
        .outerjoin(PaymentFailure, PaymentFailure.payment_id == Payment.id)
    )


def _to_opportunity_read(
    selector: RecoveryActionSelector, prediction: RecoveryPrediction,
    payment: Payment, failure: PaymentFailure | None, *, policy, spike_map,
) -> RecoveryOpportunityRead:
    """Recommended action comes from the same `RecoveryActionSelector` that
    campaign creation uses (see campaign_service.get_or_refresh_opportunity)
    -- this endpoint previously had its own, separate, less-safe derivation
    (`_derive_recommended_action`) that silently fell through to
    PAYMENT_LINK for an unrecognized failure category. That duplicate
    policy system is gone; there is now exactly one place action
    recommendations are decided."""
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=prediction.recovery_probability,
        expected_recovery=prediction.expected_recovery, confidence=prediction.confidence,
        policy=policy, spike_map=spike_map,
    )

    return RecoveryOpportunityRead(
        **RecoveryPredictionRead.model_validate(prediction).model_dump(),
        amount=payment.amount,
        currency=payment.currency,
        customer_id=payment.customer_id,
        payment_method=payment.method.value,
        failure_category=failure.failure_category.value if failure else None,
        recommended_action=decision.action.value,
        reason=decision.reason,
        created_at=payment.created_at,
    )


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(session: Session = Depends(get_session)) -> AnalyzeResponse:
    """Runs the prediction pipeline against every currently-failed payment
    and (re)persists a recovery_predictions row for each."""
    try:
        results = analyze_all_failed_payments(session)
    except ModelNotTrainedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not results:
        return AnalyzeResponse(
            analyzed_count=0, high_recovery_count=0, medium_recovery_count=0,
            low_recovery_count=0, total_expected_recovery=0.0,
            model_name="", model_version="", feature_version="", training_timestamp=None,
        )

    counts = {RecoverySegment.HIGH_RECOVERY.value: 0, RecoverySegment.MEDIUM_RECOVERY.value: 0, RecoverySegment.LOW_RECOVERY.value: 0}
    for r in results:
        counts[r["segment"]] += 1

    return AnalyzeResponse(
        analyzed_count=len(results),
        high_recovery_count=counts[RecoverySegment.HIGH_RECOVERY.value],
        medium_recovery_count=counts[RecoverySegment.MEDIUM_RECOVERY.value],
        low_recovery_count=counts[RecoverySegment.LOW_RECOVERY.value],
        total_expected_recovery=round(sum(r["expected_recovery"] for r in results), 2),
        model_name=results[0]["model_name"],
        model_version=results[0]["model_version"],
        feature_version=results[0]["feature_version"],
        training_timestamp=results[0]["training_timestamp"],
    )


@router.get("/metrics", response_model=RecoveryMetricsRead)
def get_metrics(session: Session = Depends(get_session)) -> RecoveryMetricsRead:
    """Portfolio-wide revenue-at-risk / recoverable / recovered / recovery-rate
    (spec section 7). Per-campaign metrics are on `GET /api/recovery/campaigns/{id}`."""
    metrics = compute_portfolio_metrics(session)
    return RecoveryMetricsRead(**metrics.as_dict())


@router.get("/opportunities", response_model=PaginatedRecoveryOpportunities)
def list_opportunities(
    session: Session = Depends(get_session),
    segment: RecoverySegment | None = None,
    limit: int = Query(default=50, le=500, gt=0),
    offset: int = Query(default=0, ge=0),
) -> PaginatedRecoveryOpportunities:
    """Ranked by `expected_recovery` (amount x recovery_probability), not
    raw transaction amount -- see docs/ml-evaluation.md for why."""
    query = _opportunity_query()
    count_query = select(func.count()).select_from(RecoveryPrediction)
    if segment is not None:
        query = query.where(RecoveryPrediction.segment == segment)
        count_query = count_query.where(RecoveryPrediction.segment == segment)

    total = session.exec(count_query).one()
    rows = session.exec(
        query.order_by(RecoveryPrediction.expected_recovery.desc()).limit(limit).offset(offset)
    ).all()

    # Both computed once for the whole page, not once per row -- see
    # compute_category_spike_map's docstring for why a per-row version of
    # either would be an N+1 query pattern.
    policy = session.exec(select(MerchantPolicy)).first()
    spike_map = compute_category_spike_map(session)
    selector = RecoveryActionSelector(session)

    items = [
        _to_opportunity_read(selector, pred, payment, failure, policy=policy, spike_map=spike_map)
        for pred, payment, failure in rows
    ]
    return PaginatedRecoveryOpportunities(total=total, limit=limit, offset=offset, items=items)


@router.get("/opportunities/{payment_id}", response_model=RecoveryOpportunityRead)
def get_opportunity(payment_id: uuid.UUID, session: Session = Depends(get_session)) -> RecoveryOpportunityRead:
    row = session.exec(
        _opportunity_query().where(RecoveryPrediction.payment_id == payment_id)
    ).first()

    if row is None:
        # Not analyzed yet -- compute it on demand rather than 404ing.
        try:
            predict_recovery(payment_id, session)
        except ModelNotTrainedError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PaymentNotEligibleError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        row = session.exec(
            _opportunity_query().where(RecoveryPrediction.payment_id == payment_id)
        ).first()

    prediction, payment, failure = row
    policy = session.exec(select(MerchantPolicy)).first()
    spike_map = compute_category_spike_map(session)
    selector = RecoveryActionSelector(session)
    return _to_opportunity_read(selector, prediction, payment, failure, policy=policy, spike_map=spike_map)
