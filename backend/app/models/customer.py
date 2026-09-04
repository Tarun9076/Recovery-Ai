import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.merchant import Merchant
    from app.models.order import Order
    from app.models.payment import Payment


class Customer(SQLModel, table=True):
    __tablename__ = "customers"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    merchant_id: uuid.UUID = Field(foreign_key="merchants.id", index=True)

    name: str
    email: str = Field(index=True)
    phone: str

    customer_since: datetime
    lifetime_value: float = Field(default=0)
    order_count: int = Field(default=0)
    successful_payment_count: int = Field(default=0)
    failed_payment_count: int = Field(default=0)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    merchant: Optional["Merchant"] = Relationship(back_populates="customers")
    orders: list["Order"] = Relationship(back_populates="customer")
    payments: list["Payment"] = Relationship(back_populates="customer")
