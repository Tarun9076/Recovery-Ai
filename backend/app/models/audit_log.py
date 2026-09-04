import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Enum as SAEnum, JSON
from sqlmodel import Field, SQLModel

from app.models.enums import AuditEventType


class AuditLog(SQLModel, table=True):
    """General-purpose audit trail for the campaign/approval workflow
    (distinct from Phase 3's `ai_investigations`, which audits investigation
    runs specifically). `details` never contains secrets or credentials --
    nothing in this workflow ever touches any."""

    __tablename__ = "audit_logs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    # values_callable is required here: AuditEventType's member *names*
    # (CAMPAIGN_CREATED) deliberately differ from its *values*
    # (campaign_created, matching the spec's exact event-name strings) --
    # without it, SQLAlchemy's auto-generated Postgres ENUM stores the
    # member name instead of the value.
    event_type: AuditEventType = Field(
        sa_column=Column(SAEnum(AuditEventType, values_callable=lambda enum_cls: [e.value for e in enum_cls]), index=True)
    )
    actor: str

    entity_type: str
    entity_id: uuid.UUID = Field(index=True)

    details: dict = Field(default_factory=dict, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
