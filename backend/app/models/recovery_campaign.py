import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import CampaignStatus

if TYPE_CHECKING:
    from app.models.merchant import Merchant
    from app.models.recovery_action import RecoveryAction


class RecoveryCampaign(SQLModel, table=True):
    """A merchant-approved batch of recovery actions. Everything here is
    computed and revalidated by the backend at creation time (see
    `campaign_service.create_campaign`) -- never taken from the frontend.

    No `recovered_amount` field exists here, deliberately: a campaign
    reaching COMPLETED means every action's mock payment link was created,
    not that any customer actually paid (spec section 11) -- there is no
    real payment confirmation mechanism until a later phase, so nothing in
    this codebase may claim revenue was recovered.
    """

    __tablename__ = "recovery_campaigns"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    merchant_id: uuid.UUID = Field(foreign_key="merchants.id", index=True)

    name: str

    target_count: int
    total_amount: float
    expected_recovery: float

    status: CampaignStatus = Field(default=CampaignStatus.PENDING_APPROVAL, index=True)

    created_by: str
    approved_by: Optional[str] = Field(default=None)
    rejection_reason: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)

    merchant: Optional["Merchant"] = Relationship()
    actions: list["RecoveryAction"] = Relationship(back_populates="campaign")
