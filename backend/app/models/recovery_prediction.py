import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import RecoverySegment

if TYPE_CHECKING:
    from app.models.payment import Payment


class RecoveryPrediction(SQLModel, table=True):
    """The latest recovery-probability prediction for a failed payment.

    One row per payment (upserted by `POST /api/recovery/analyze`) rather
    than a history table -- Phase 2 only needs "the current prediction",
    not an audit trail of every past prediction run.
    """

    __tablename__ = "recovery_predictions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    payment_id: uuid.UUID = Field(foreign_key="payments.id", unique=True, index=True)

    recovery_probability: float
    expected_recovery: float
    confidence: float
    segment: RecoverySegment = Field(index=True)

    top_factors: list[dict] = Field(default_factory=list, sa_column=Column(JSON))

    model_name: str
    model_version: str
    feature_version: str
    training_timestamp: datetime

    predicted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    payment: Optional["Payment"] = Relationship()
