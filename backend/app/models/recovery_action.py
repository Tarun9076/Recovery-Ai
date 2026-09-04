import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import RecommendedAction, RecoveryActionStatus

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.payment import Payment
    from app.models.recovery_campaign import RecoveryCampaign
    from app.models.recovery_opportunity import RecoveryOpportunity


class RecoveryAction(SQLModel, table=True):
    """One per-payment line item within a campaign. `provider_response` is
    whatever `PaymentProvider.create_recovery_link()` (mock or real
    Razorpay test-mode) returned -- a link being created is recorded here
    as EXECUTED, which is NOT the same claim as "recovered" (see
    RecoveryCampaign's docstring). `recovered_amount`/`recovered_at` are
    set *only* by `app/api/webhooks.py` after cryptographically verifying
    an inbound Razorpay webhook confirms this specific payment link was
    paid -- no other code path may ever populate them."""

    __tablename__ = "recovery_actions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    campaign_id: uuid.UUID = Field(foreign_key="recovery_campaigns.id", index=True)
    opportunity_id: uuid.UUID = Field(foreign_key="recovery_opportunities.id", index=True)
    payment_id: uuid.UUID = Field(foreign_key="payments.id", index=True)
    customer_id: uuid.UUID = Field(foreign_key="customers.id", index=True)

    action_type: RecommendedAction
    status: RecoveryActionStatus = Field(default=RecoveryActionStatus.PENDING, index=True)

    provider_response: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    # Denormalized out of `provider_response` (the audit record of record)
    # and indexed so an inbound webhook can look up "which action does this
    # payment link belong to" with a single indexed query instead of
    # loading every EXECUTED/RECOVERED action into Python to filter a JSON
    # field in-memory (see webhook_service._find_action_by_payment_link_id,
    # fixed in Phase 8's performance pass -- the original in-memory version
    # would not scale past a few thousand recovery actions).
    payment_link_id: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    authorized_at: Optional[datetime] = Field(default=None)
    executed_at: Optional[datetime] = Field(default=None)
    recovered_at: Optional[datetime] = Field(default=None)
    recovered_amount: Optional[float] = Field(default=None)

    campaign: Optional["RecoveryCampaign"] = Relationship(back_populates="actions")
    opportunity: Optional["RecoveryOpportunity"] = Relationship()
    payment: Optional["Payment"] = Relationship()
    customer: Optional["Customer"] = Relationship()
