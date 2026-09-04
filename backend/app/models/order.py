import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import OrderStatus

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.merchant import Merchant
    from app.models.payment import Payment


class Order(SQLModel, table=True):
    __tablename__ = "orders"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    merchant_id: uuid.UUID = Field(foreign_key="merchants.id", index=True)
    customer_id: uuid.UUID = Field(foreign_key="customers.id", index=True)

    amount: float
    currency: str = Field(default="INR")
    status: OrderStatus = Field(default=OrderStatus.created, index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    merchant: Optional["Merchant"] = Relationship(back_populates="orders")
    customer: Optional["Customer"] = Relationship(back_populates="orders")
    payments: list["Payment"] = Relationship(back_populates="order")
