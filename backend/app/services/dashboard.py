from sqlalchemy import case, func
from sqlmodel import Session, select

from app.models.customer import Customer
from app.models.enums import PaymentStatus
from app.models.merchant import Merchant
from app.models.order import Order
from app.models.payment import Payment
from app.schemas.dashboard import (
    DashboardSummary,
    FailureCategoryBreakdown,
    FailureTrendPoint,
)

FAILED_STATUSES = (PaymentStatus.failed,)
# A refunded payment succeeded before being refunded, so it belongs in the
# success bucket, not left uncounted against either bucket.
SUCCESS_STATUSES = (
    PaymentStatus.success,
    PaymentStatus.captured,
    PaymentStatus.authorized,
    PaymentStatus.refunded,
)


def get_dashboard_summary(session: Session) -> DashboardSummary:
    total_payments = session.exec(select(func.count()).select_from(Payment)).one()

    successful_payments = session.exec(
        select(func.count()).select_from(Payment).where(Payment.status.in_(SUCCESS_STATUSES))
    ).one()

    failed_payments = session.exec(
        select(func.count()).select_from(Payment).where(Payment.status.in_(FAILED_STATUSES))
    ).one()

    total_transaction_value = session.exec(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status.in_(SUCCESS_STATUSES))
    ).one()

    failed_transaction_value = session.exec(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status.in_(FAILED_STATUSES))
    ).one()

    failure_rate = (failed_payments / total_payments) if total_payments else 0.0

    total_merchants = session.exec(select(func.count()).select_from(Merchant)).one()
    total_customers = session.exec(select(func.count()).select_from(Customer)).one()
    total_orders = session.exec(select(func.count()).select_from(Order)).one()

    failed_case = case((Payment.status.in_(FAILED_STATUSES), 1), else_=0)
    trend_rows = session.exec(
        select(
            func.date(Payment.created_at).label("day"),
            func.count().label("total"),
            func.sum(failed_case).label("failed"),
        )
        .group_by(func.date(Payment.created_at))
        .order_by(func.date(Payment.created_at))
    ).all()

    failure_trend = [
        FailureTrendPoint(
            date=str(row.day),
            total_payments=row.total,
            failed_payments=row.failed or 0,
            failure_rate=round((row.failed or 0) / row.total, 4) if row.total else 0.0,
        )
        for row in trend_rows
    ]

    breakdown = _failure_category_breakdown(session)

    return DashboardSummary(
        total_payments=total_payments,
        successful_payments=successful_payments,
        failed_payments=failed_payments,
        total_transaction_value=float(total_transaction_value or 0),
        failed_transaction_value=float(failed_transaction_value or 0),
        failure_rate=round(failure_rate, 4),
        total_merchants=total_merchants,
        total_customers=total_customers,
        total_orders=total_orders,
        failure_trend=failure_trend,
        failure_category_breakdown=breakdown,
    )


def _failure_category_breakdown(session: Session) -> list[FailureCategoryBreakdown]:
    from app.models.payment_failure import PaymentFailure

    rows = session.exec(
        select(PaymentFailure.failure_category, func.count())
        .group_by(PaymentFailure.failure_category)
        .order_by(func.count().desc())
    ).all()
    return [FailureCategoryBreakdown(failure_category=cat, count=count) for cat, count in rows]
