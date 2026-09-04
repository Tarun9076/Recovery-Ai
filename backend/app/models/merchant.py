import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.merchant_policy import MerchantPolicy
    from app.models.order import Order
    from app.models.payment import Payment


class Merchant(SQLModel, table=True):
    __tablename__ = "merchants"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    email: str = Field(unique=True, index=True)
    business_name: str
    currency: str = Field(default="INR")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    customers: list["Customer"] = Relationship(back_populates="merchant")
    orders: list["Order"] = Relationship(back_populates="merchant")
    payments: list["Payment"] = Relationship(back_populates="merchant")
    policy: "MerchantPolicy" = Relationship(back_populates="merchant")
