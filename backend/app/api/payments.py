import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models.enums import PaymentStatus
from app.models.payment import Payment
from app.models.payment_failure import PaymentFailure
from app.schemas.payment import (
    FailedPaymentRead,
    PaginatedFailedPayments,
    PaginatedPayments,
    PaymentRead,
)

router = APIRouter(prefix="/api/payments", tags=["payments"])


@router.get("", response_model=PaginatedPayments)
def list_payments(
    session: Session = Depends(get_session),
    status: PaymentStatus | None = None,
    customer_id: uuid.UUID | None = None,
    limit: int = Query(default=50, le=500, gt=0),
    offset: int = Query(default=0, ge=0),
) -> PaginatedPayments:
    query = select(Payment)
    count_query = select(func.count()).select_from(Payment)

    if status is not None:
        query = query.where(Payment.status == status)
        count_query = count_query.where(Payment.status == status)
    if customer_id is not None:
        query = query.where(Payment.customer_id == customer_id)
        count_query = count_query.where(Payment.customer_id == customer_id)

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(Payment.created_at.desc()).limit(limit).offset(offset)
    ).all()

    return PaginatedPayments(total=total, limit=limit, offset=offset, items=items)


@router.get("/failed", response_model=PaginatedFailedPayments)
def list_failed_payments(
    session: Session = Depends(get_session),
    customer_id: uuid.UUID | None = None,
    limit: int = Query(default=50, le=500, gt=0),
    offset: int = Query(default=0, ge=0),
) -> PaginatedFailedPayments:
    query = select(Payment).where(Payment.status == PaymentStatus.failed)
    count_query = (
        select(func.count()).select_from(Payment).where(Payment.status == PaymentStatus.failed)
    )

    if customer_id is not None:
        query = query.where(Payment.customer_id == customer_id)
        count_query = count_query.where(Payment.customer_id == customer_id)

    total = session.exec(count_query).one()
    payments = session.exec(
        query.order_by(Payment.created_at.desc()).limit(limit).offset(offset)
    ).all()

    payment_ids = [p.id for p in payments]
    failures_by_payment: dict[uuid.UUID, PaymentFailure] = {}
    if payment_ids:
        failures = session.exec(
            select(PaymentFailure).where(PaymentFailure.payment_id.in_(payment_ids))
        ).all()
        failures_by_payment = {f.payment_id: f for f in failures}

    items = [
        FailedPaymentRead(
            **PaymentRead.model_validate(p).model_dump(),
            failure=failures_by_payment.get(p.id),
        )
        for p in payments
    ]

    return PaginatedFailedPayments(total=total, limit=limit, offset=offset, items=items)


@router.get("/{payment_id}", response_model=FailedPaymentRead)
def get_payment(payment_id: uuid.UUID, session: Session = Depends(get_session)) -> FailedPaymentRead:
    payment = session.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    failure = session.exec(
        select(PaymentFailure).where(PaymentFailure.payment_id == payment_id)
    ).first()
    return FailedPaymentRead(**PaymentRead.model_validate(payment).model_dump(), failure=failure)
