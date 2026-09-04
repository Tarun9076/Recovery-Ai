import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import (
    DeviceType,
    FailureSource,
    FailureStep,
    PaymentMethod,
    PaymentStatus,
    Platform,
)

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.merchant import Merchant
    from app.models.order import Order
    from app.models.payment_failure import PaymentFailure


class Payment(SQLModel, table=True):
    __tablename__ = "payments"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    merchant_id: uuid.UUID = Field(foreign_key="merchants.id", index=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", index=True)
    customer_id: uuid.UUID = Field(foreign_key="customers.id", index=True)

    razorpay_payment_id: str = Field(unique=True, index=True)

    amount: float
    currency: str = Field(default="INR")

    status: PaymentStatus = Field(index=True)

    method: PaymentMethod
    bank: Optional[str] = Field(default=None)
    wallet: Optional[str] = Field(default=None)
    vpa: Optional[str] = Field(default=None)

    email: str
    contact: str

    device_type: DeviceType
    platform: Platform
    location: str

    attempt_number: int = Field(default=1)

    failure_code: Optional[str] = Field(default=None)
    failure_reason: Optional[str] = Field(default=None)
    failure_source: Optional[FailureSource] = Field(default=None)
    failure_step: Optional[FailureStep] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    merchant: Optional["Merchant"] = Relationship(back_populates="payments")
    order: Optional["Order"] = Relationship(back_populates="payments")
    customer: Optional["Customer"] = Relationship(back_populates="payments")
    failure: Optional["PaymentFailure"] = Relationship(back_populates="payment")
