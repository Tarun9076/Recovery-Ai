import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    AuditEventType,
    CampaignStatus,
    OpportunityStatus,
    RecommendedAction,
    RecoveryActionStatus,
)


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    payment_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    created_by: str = Field(default="merchant", min_length=1, max_length=200)


class CampaignApproveRequest(BaseModel):
    approved_by: str = Field(default="merchant", min_length=1, max_length=200)


class CampaignRejectRequest(BaseModel):
    rejected_by: str = Field(default="merchant", min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)


class RecoveryActionRead(BaseModel):
    id: uuid.UUID
    payment_id: uuid.UUID
    customer_id: uuid.UUID
    action_type: RecommendedAction
    status: RecoveryActionStatus
    provider_response: dict | None = None
    created_at: datetime
    authorized_at: datetime | None = None
    executed_at: datetime | None = None
    recovered_at: datetime | None = None
    recovered_amount: float | None = None

    model_config = {"from_attributes": True}


class OpportunitySummary(BaseModel):
    payment_id: uuid.UUID
    customer_id: uuid.UUID
    recovery_probability: float
    expected_recovery: float
    recommended_action: RecommendedAction
    reason: str
    confidence: float
    status: OpportunityStatus


class AuditLogRead(BaseModel):
    """Phase 8 (spec: "easily-demonstrable audit trail"). One raw
    `audit_logs` row -- `event_type` names exactly which step of
    "AI concluded -> merchant approved -> system executed -> what actually
    happened" this is (see app.models.enums.AuditEventType)."""

    id: uuid.UUID
    event_type: AuditEventType
    actor: str
    entity_type: str
    entity_id: uuid.UUID
    details: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class CampaignRead(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    name: str
    target_count: int
    total_amount: float
    expected_recovery: float
    status: CampaignStatus
    created_by: str
    approved_by: str | None = None
    rejection_reason: str | None = None
    created_at: datetime
    approved_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class CampaignDetailRead(CampaignRead):
    recommendations: list[OpportunitySummary] = Field(default_factory=list)
    actions: list[RecoveryActionRead] = Field(default_factory=list)
    audit_trail: list[AuditLogRead] = Field(default_factory=list)

    # Computed fresh from this campaign's actions on every read (spec
    # section 7) -- never a stored/cached total, so it can't drift from
    # what webhook_service.py has actually confirmed. revenue_at_risk and
    # recoverable_revenue duplicate total_amount/expected_recovery under
    # the spec's own metric names, for a self-contained response.
    revenue_at_risk: float
    recoverable_revenue: float
    revenue_recovered: float
    recovery_rate: float


class CampaignCreateResponse(BaseModel):
    campaign: CampaignRead
    excluded: list[dict] = Field(default_factory=list)


class PaginatedCampaigns(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CampaignRead]
