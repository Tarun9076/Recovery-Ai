import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.enums import (
    DeviceType,
    FailureCategory,
    FailureSeverity,
    FailureSource,
    FailureStep,
    PaymentMethod,
    PaymentStatus,
    Platform,
    Recoverability,
)


class PaymentFailureRead(BaseModel):
    """Public view of a normalized failure. Ground truth (`eventually_recovered`)
    is intentionally omitted — it must never be exposed as a prediction feature."""

    failure_category: FailureCategory
    failure_severity: FailureSeverity
    recoverability: Recoverability
    raw_failure_code: str
    raw_failure_reason: str

    model_config = {"from_attributes": True}


class PaymentRead(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    order_id: uuid.UUID
    customer_id: uuid.UUID

    razorpay_payment_id: str

    amount: float
    currency: str
    status: PaymentStatus

    method: PaymentMethod
    bank: Optional[str] = None
    wallet: Optional[str] = None
    vpa: Optional[str] = None

    email: str
    contact: str

    device_type: DeviceType
    platform: Platform
    location: str

    attempt_number: int

    failure_code: Optional[str] = None
    failure_reason: Optional[str] = None
    failure_source: Optional[FailureSource] = None
    failure_step: Optional[FailureStep] = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FailedPaymentRead(PaymentRead):
    failure: Optional[PaymentFailureRead] = None


class PaginatedPayments(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PaymentRead]


class PaginatedFailedPayments(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[FailedPaymentRead]
