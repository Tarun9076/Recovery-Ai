import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import FailureCategory, FailureSeverity, Recoverability

if TYPE_CHECKING:
    from app.models.payment import Payment


class PaymentFailure(SQLModel, table=True):
    """Normalized failure record for a failed payment attempt.

    `eventually_recovered` is ground truth for future ML training/evaluation
    only. It must never be surfaced as a prediction input feature.
    """

    __tablename__ = "payment_failures"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    payment_id: uuid.UUID = Field(foreign_key="payments.id", unique=True, index=True)

    failure_category: FailureCategory = Field(index=True)
    failure_severity: FailureSeverity
    recoverability: Recoverability

    raw_failure_code: str
    raw_failure_reason: str

    eventually_recovered: bool = Field(default=False)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    payment: Optional["Payment"] = Relationship(back_populates="failure")
