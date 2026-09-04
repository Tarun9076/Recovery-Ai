import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.merchant import Merchant


class MerchantPolicy(SQLModel, table=True):
    __tablename__ = "merchant_policies"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    merchant_id: uuid.UUID = Field(foreign_key="merchants.id", unique=True, index=True)

    minimum_recovery_probability: float = Field(default=0.65)
    max_customer_contacts: int = Field(default=1)
    max_campaign_amount: Optional[float] = Field(default=None)

    approval_required: bool = Field(default=True)

    allowed_actions: list[str] = Field(
        default_factory=lambda: ["email", "sms", "whatsapp"],
        sa_column=Column(JSON),
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    merchant: Optional["Merchant"] = Relationship(back_populates="policy")
