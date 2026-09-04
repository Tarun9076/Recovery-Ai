import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel


class WebhookEvent(SQLModel, table=True):
    """Every inbound webhook this backend receives, verified or not.
    `event_id` is Razorpay's `x-razorpay-event-id` header when present (the
    documented dedup key); if a request arrives without it, a hash of the
    body+signature is used instead so an exact-duplicate delivery still
    dedups. The `(provider, event_id)` unique constraint makes idempotency
    a database guarantee, not just an application-level check-then-insert
    (which would race under concurrent redelivery).

    An event with a bad signature is still stored here (signature_verified
    = False, processed = False, forever) -- for audit visibility into
    spoofed/misconfigured attempts -- but `webhook_service.py` never acts
    on it; only a verified event can reach `processed = True`.
    """

    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_webhook_events_provider_event_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    provider: str = Field(index=True)
    event_type: str
    event_id: str = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))

    signature_verified: bool
    processed: bool = Field(default=False, index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    processed_at: Optional[datetime] = Field(default=None)
