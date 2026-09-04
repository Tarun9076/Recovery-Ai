"""The agent's entire universe of database access.

Every one of these eight functions is the *only* way the investigation
agent (or the LLM it drives) can touch data -- there is no raw session/SQL
access anywhere else in `revenue_recovery_agent.py`, and none of these
functions ever writes to `payments`, `orders`, or `merchant_policies`. Each
returns plain, already-computed dicts/lists (never a SQLAlchemy/SQLModel
object), which is also exactly what's safe to drop into an LLM prompt or an
audit log.

The LLM itself never calls these -- see `revenue_recovery_agent.py`'s
module docstring for why (short version: an LLM given real tool-calling
access could construct a query that invents or distorts a statistic; a
fixed deterministic pipeline over these functions cannot).
"""

from __future__ import annotations

import statistics
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.customer import Customer
from app.models.enums import FailureCategory, PaymentStatus
from app.models.merchant_policy import MerchantPolicy
from app.models.payment import Payment
from app.models.payment_failure import PaymentFailure
from app.models.recovery_prediction import RecoveryPrediction
from app.services import recovery_predictor

SUCCESS_LIKE = (
    PaymentStatus.success, PaymentStatus.captured, PaymentStatus.authorized, PaymentStatus.refunded,
)


def _row_to_dict(payment: Payment, failure: PaymentFailure | None = None) -> dict:
    return {
        "payment_id": str(payment.id),
        "customer_id": str(payment.customer_id),
        "amount": payment.amount,
        "currency": payment.currency,
        "status": payment.status.value,
        "method": payment.method.value,
        "bank": payment.bank,
        "attempt_number": payment.attempt_number,
        "created_at": payment.created_at.isoformat(),
        "failure_category": failure.failure_category.value if failure else None,
        "failure_severity": failure.failure_severity.value if failure else None,
    }


def get_failed_payments(
    session: Session, *,
    since: datetime | None = None, until: datetime | None = None,
    category: str | None = None, bank: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Recent failed payments (most recent first) in an optional window,
    optionally restricted to a failure category and/or bank -- how
    RootCauseAnalyzer pulls the exact payments behind one finding."""
    query = select(Payment, PaymentFailure).join(
        PaymentFailure, PaymentFailure.payment_id == Payment.id
    ).where(Payment.status == PaymentStatus.failed)
    if since is not None:
        query = query.where(Payment.created_at >= since)
    if until is not None:
        query = query.where(Payment.created_at <= until)
    if category is not None:
        query = query.where(PaymentFailure.failure_category == FailureCategory(category))
    if bank is not None:
        query = query.where(Payment.bank == bank)
    rows = session.exec(query.order_by(Payment.created_at.desc()).limit(limit)).all()
    return [_row_to_dict(p, f) for p, f in rows]


def get_payment_details(session: Session, payment_id: uuid.UUID) -> dict | None:
    """A single payment plus its failure record, if any."""
    payment = session.get(Payment, payment_id)
    if payment is None:
        return None
    failure = session.exec(
        select(PaymentFailure).where(PaymentFailure.payment_id == payment_id)
    ).first()
    return _row_to_dict(payment, failure)


def get_customer_history(session: Session, customer_id: uuid.UUID) -> dict | None:
    """A customer's aggregate order/payment history (Phase 1's already-
    consistent summary columns -- not point-in-time, this is for merchant-
    facing context, not model features)."""
    customer = session.get(Customer, customer_id)
    if customer is None:
        return None
    return {
        "customer_id": str(customer.id),
        "customer_since": customer.customer_since.isoformat(),
        "lifetime_value": customer.lifetime_value,
        "order_count": customer.order_count,
        "successful_payment_count": customer.successful_payment_count,
        "failed_payment_count": customer.failed_payment_count,
    }


def get_failure_statistics(
    session: Session, *, since: datetime | None = None, until: datetime | None = None
) -> dict:
    """Aggregate payment/failure counts and breakdowns for a window
    (defaults to the entire dataset). This is the "retrieve payment
    statistics" + "break down by category/method" step of the investigation
    flow.

    Computed entirely as SQL aggregates (COUNT/SUM/GROUP BY) -- no row is
    ever fetched into Python just to be counted or summed. At 100k+ rows,
    loading the whole `payments` table as ORM objects for this (the
    original implementation) is exactly the "loading the entire database
    into memory for a normal API call" anti-pattern this needs to avoid.
    """
    window_filters = []
    if since is not None:
        window_filters.append(Payment.created_at >= since)
    if until is not None:
        window_filters.append(Payment.created_at <= until)

    total = session.exec(select(func.count()).select_from(Payment).where(*window_filters)).one()
    failed_count = session.exec(
        select(func.count()).select_from(Payment).where(*window_filters, Payment.status == PaymentStatus.failed)
    ).one()
    total_amount = session.exec(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(*window_filters)
    ).one()
    failed_amount = session.exec(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(*window_filters, Payment.status == PaymentStatus.failed)
    ).one()

    def _breakdown(column) -> list[dict]:
        rows = session.exec(
            select(column, func.count())
            .where(*window_filters, Payment.status == PaymentStatus.failed)
            .group_by(column)
        ).all()
        return sorted(
            [
                {
                    "key": (key.value if hasattr(key, "value") else key) or "NONE",
                    "count": count,
                    "share": count / failed_count if failed_count else 0.0,
                }
                for key, count in rows
            ],
            key=lambda r: r["count"], reverse=True,
        )

    return {
        "window": {
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
        "total_payments": total,
        "failed_payments": failed_count,
        "failure_rate": failed_count / total if total else 0.0,
        "total_amount": float(total_amount),
        "failed_amount": float(failed_amount),
        "method_breakdown": _breakdown(Payment.method),
        "bank_breakdown": _breakdown(Payment.bank),
    }


def analyze_failure_spike(
    session: Session, *, recent_days: int = 7, baseline_days: int = 21, as_of: datetime | None = None
) -> dict:
    """Compares a recent window against the period immediately preceding it
    and flags failure-category / bank / hour-of-day concentrations that grew
    disproportionately -- the "compare current vs baseline", "abnormal
    patterns", "bank concentration", "time concentration" steps.

    `as_of` should be naive UTC, matching how `payments.created_at` is
    stored (Phase 1 stamped it with `datetime.now(timezone.utc)` but the
    column itself is timezone-naive) -- defaults to the latest payment in
    the database rather than wall-clock time, since this is a fixed
    historical dataset that shouldn't drift out of its own "recent window"
    the longer it sits unrefreshed.
    """
    if as_of is None:
        as_of = get_latest_payment_timestamp(session) or datetime.now(timezone.utc).replace(tzinfo=None)
    recent_start = as_of - timedelta(days=recent_days)
    baseline_start = recent_start - timedelta(days=baseline_days)

    recent_stats = get_failure_statistics(session, since=recent_start, until=as_of)
    baseline_stats = get_failure_statistics(session, since=baseline_start, until=recent_start)

    failure_rate_change_pct = (
        (recent_stats["failure_rate"] - baseline_stats["failure_rate"]) / baseline_stats["failure_rate"]
        if baseline_stats["failure_rate"] else None
    )

    category_query = (
        select(PaymentFailure.failure_category, func.count())
        .join(Payment, Payment.id == PaymentFailure.payment_id)
        .where(Payment.created_at >= recent_start, Payment.created_at <= as_of)
        .group_by(PaymentFailure.failure_category)
    )
    recent_categories = dict(session.exec(category_query).all())
    baseline_category_query = (
        select(PaymentFailure.failure_category, func.count())
        .join(Payment, Payment.id == PaymentFailure.payment_id)
        .where(Payment.created_at >= baseline_start, Payment.created_at < recent_start)
        .group_by(PaymentFailure.failure_category)
    )
    baseline_categories = dict(session.exec(baseline_category_query).all())

    recent_failed_total = max(recent_stats["failed_payments"], 1)
    baseline_failed_total = max(baseline_stats["failed_payments"], 1)

    category_breakdown = []
    anomalies: list[dict] = []
    for category in set(recent_categories) | set(baseline_categories):
        recent_count = recent_categories.get(category, 0)
        baseline_count = baseline_categories.get(category, 0)
        recent_share = recent_count / recent_failed_total
        baseline_share = baseline_count / baseline_failed_total
        row = {
            "category": category.value if hasattr(category, "value") else str(category),
            "recent_count": recent_count,
            "recent_share": recent_share,
            "baseline_share": baseline_share,
        }
        category_breakdown.append(row)
        if recent_count >= 10 and baseline_share > 0 and recent_share > baseline_share * 1.5:
            anomalies.append({
                "type": "category_spike",
                "category": row["category"],
                "recent_share": recent_share,
                "baseline_share": baseline_share,
                "recent_count": recent_count,
            })
    category_breakdown.sort(key=lambda r: r["recent_count"], reverse=True)

    # Bank concentration among recent failures (any category)
    bank_query = (
        select(Payment.bank, func.count())
        .where(Payment.status == PaymentStatus.failed, Payment.created_at >= recent_start, Payment.created_at <= as_of, Payment.bank.is_not(None))
        .group_by(Payment.bank)
    )
    bank_counts = dict(session.exec(bank_query).all())
    bank_concentration = sorted(
        [{"bank": b, "recent_failed_count": c, "recent_failed_share": c / recent_failed_total} for b, c in bank_counts.items()],
        key=lambda r: r["recent_failed_count"], reverse=True,
    )
    overall_bank_share = 1 / max(len(bank_counts), 1)
    for row in bank_concentration:
        if row["recent_failed_count"] >= 10 and row["recent_failed_share"] > overall_bank_share * 2.5:
            anomalies.append({
                "type": "bank_concentration",
                "bank": row["bank"],
                "recent_failed_share": row["recent_failed_share"],
                "recent_failed_count": row["recent_failed_count"],
            })

    # Time concentration: failure rate by day within the recent window
    day_query = (
        select(func.date(Payment.created_at), func.count())
        .where(Payment.status == PaymentStatus.failed, Payment.created_at >= recent_start, Payment.created_at <= as_of)
        .group_by(func.date(Payment.created_at))
    )
    day_counts = {str(d): c for d, c in session.exec(day_query).all()}
    time_concentration = []
    if len(day_counts) >= 3:
        counts = list(day_counts.values())
        mean = statistics.mean(counts)
        stdev = statistics.pstdev(counts) or 1.0
        for day, count in sorted(day_counts.items()):
            z = (count - mean) / stdev
            time_concentration.append({"date": day, "failed_count": count, "z_score": round(z, 2)})
            if z >= 2.0:
                anomalies.append({"type": "time_spike", "date": day, "failed_count": count, "z_score": round(z, 2)})

    return {
        "recent_window": {"since": recent_start.isoformat(), "until": as_of.isoformat(), **recent_stats},
        "baseline_window": {"since": baseline_start.isoformat(), "until": recent_start.isoformat(), **baseline_stats},
        "failure_rate_change_pct": failure_rate_change_pct,
        "category_breakdown": category_breakdown,
        "bank_concentration": bank_concentration,
        "time_concentration": time_concentration,
        "anomalies": anomalies,
    }


def predict_recovery(session: Session, payment_id: uuid.UUID) -> dict:
    """Delegates to the Phase 2 recovery-prediction service for one payment."""
    return recovery_predictor.predict_recovery(payment_id, session)


def rank_recovery_opportunities(
    session: Session, *, payment_ids: list[uuid.UUID] | None = None, limit: int = 20,
) -> list[dict]:
    """Top failed payments ranked by expected_recovery (amount x
    probability), optionally restricted to a specific set of payment_ids
    (e.g. the payments behind one finding). Runs predictions for any of
    those payments that don't have one yet."""
    if payment_ids is not None:
        existing = session.exec(
            select(RecoveryPrediction.payment_id).where(RecoveryPrediction.payment_id.in_(payment_ids))
        ).all()
        missing = [pid for pid in payment_ids if pid not in set(existing)]
        if missing:
            recovery_predictor.predict_for_payment_ids(session, missing)

    query = (
        select(RecoveryPrediction, Payment)
        .join(Payment, Payment.id == RecoveryPrediction.payment_id)
    )
    if payment_ids is not None:
        query = query.where(RecoveryPrediction.payment_id.in_(payment_ids))
    rows = session.exec(query.order_by(RecoveryPrediction.expected_recovery.desc()).limit(limit)).all()

    return [
        {
            "payment_id": str(pred.payment_id),
            "customer_id": str(payment.customer_id),
            "amount": payment.amount,
            "recovery_probability": pred.recovery_probability,
            "expected_recovery": pred.expected_recovery,
            "confidence": pred.confidence,
            "segment": pred.segment.value,
        }
        for pred, payment in rows
    ]


def get_recovery_metrics(session: Session) -> dict:
    """Aggregate metrics over all currently-stored recovery predictions --
    SQL-side (COUNT/SUM/AVG/GROUP BY), not a fetch-everything-then-sum-in-
    Python loop (see get_failure_statistics's docstring for why)."""
    total_predictions = session.exec(select(func.count()).select_from(RecoveryPrediction)).one()
    if not total_predictions:
        return {
            "total_predictions": 0, "total_expected_recovery": 0.0, "average_probability": 0.0,
            "segment_counts": {}, "model_name": None, "model_version": None, "training_timestamp": None,
        }

    total_expected_recovery = session.exec(
        select(func.coalesce(func.sum(RecoveryPrediction.expected_recovery), 0.0))
    ).one()
    average_probability = session.exec(select(func.avg(RecoveryPrediction.recovery_probability))).one()
    segment_rows = session.exec(
        select(RecoveryPrediction.segment, func.count()).group_by(RecoveryPrediction.segment)
    ).all()
    latest = session.exec(
        select(RecoveryPrediction.model_name, RecoveryPrediction.model_version, RecoveryPrediction.training_timestamp).limit(1)
    ).first()

    return {
        "total_predictions": total_predictions,
        "total_expected_recovery": float(total_expected_recovery),
        "average_probability": float(average_probability) if average_probability is not None else 0.0,
        "segment_counts": {segment.value: count for segment, count in segment_rows},
        "model_name": latest[0] if latest else None,
        "model_version": latest[1] if latest else None,
        "training_timestamp": latest[2].isoformat() if latest and latest[2] else None,
    }


def get_latest_payment_timestamp(session: Session) -> datetime | None:
    """The most recent `payments.created_at` in the database. Used as the
    investigation's reference "now" instead of wall-clock time -- this is a
    fixed historical dataset, so anchoring to real time would make the
    "recent window" drift further from any actual data the longer this
    runs after the data was seeded."""
    return session.exec(select(func.max(Payment.created_at))).one()


def get_merchant_policy(session: Session) -> MerchantPolicy | None:
    """Not one of the 8 named tools, but the same restriction applies: a
    read-only lookup, never a write. Used for the policy-check gate."""
    return session.exec(select(MerchantPolicy)).first()
