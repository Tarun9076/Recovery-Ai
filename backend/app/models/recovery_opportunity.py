import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import OpportunityStatus, RecommendedAction

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.payment import Payment


class RecoveryOpportunity(SQLModel, table=True):
    """The canonical, campaign-workflow entity for a failed payment: the
    latest ML recovery probability (Phase 2) plus a policy-gated recommended
    action (Phase 3/4's `PolicyEngine`), carrying its own lifecycle status
    as it moves through review -> campaign -> approval -> execution.

    Distinct from `RecoveryPrediction` (Phase 2's raw ML output, no
    lifecycle) -- this table is what campaigns actually reference and
    mutate the status of. `recovery_probability`/`expected_recovery`/
    `recommended_action`/`reason`/`confidence` are refreshed from scratch
    every time a campaign is created from this opportunity (see
    `campaign_service.get_or_refresh_opportunity`) -- never trusted as a
    stale cache, per the "never trust frontend calculations" rule.
    """

    __tablename__ = "recovery_opportunities"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    payment_id: uuid.UUID = Field(foreign_key="payments.id", unique=True, index=True)
    customer_id: uuid.UUID = Field(foreign_key="customers.id", index=True)

    recovery_probability: float
    expected_recovery: float

    recommended_action: RecommendedAction
    reason: str
    confidence: float

    status: OpportunityStatus = Field(default=OpportunityStatus.NEW, index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    payment: Optional["Payment"] = Relationship()
    customer: Optional["Customer"] = Relationship()
