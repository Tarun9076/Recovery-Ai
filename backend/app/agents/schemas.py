"""Pydantic schemas for the investigation agent.

Every one of these is validated -- an LLM response that doesn't conform is
never returned to the caller (see `llm_client.py`'s parse-and-validate step
and its graceful fallback on failure).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# Shared with the Phase 4 opportunity/campaign workflow -- defined once in
# app.models.enums so the DB columns and this schema can never drift apart.
from app.models.enums import RecommendedAction

__all__ = [
    "Severity", "RecommendedAction", "Finding", "StructuredDecision",
    "InvestigateRequest", "InvestigateResponse", "LLMNarrative",
    "InvestigationRead", "PaginatedInvestigations",
]


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Finding(BaseModel):
    """One root-cause finding. `evidence` must be strings drawn from actual
    tool output (see revenue_recovery_agent.RootCauseAnalyzer) -- the LLM
    only ever paraphrases these, it does not generate them."""

    finding: str
    severity: Severity
    evidence: list[str] = Field(default_factory=list)
    affected_payment_count: int = Field(ge=0)
    revenue_at_risk: float = Field(ge=0)
    estimated_recoverable_revenue: float = Field(ge=0)


class StructuredDecision(BaseModel):
    """One recommended intervention. All numeric fields are computed by
    backend tools/the ML engine and are re-stamped onto this object after
    the LLM call -- the LLM cannot alter them (see
    revenue_recovery_agent.InterventionPlanner)."""

    problem: str
    root_cause: str
    evidence: list[str] = Field(default_factory=list)
    revenue_at_risk: float = Field(ge=0)
    recoverable_revenue: float = Field(ge=0)
    recommended_action: RecommendedAction
    expected_recovery: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    reason: str
    requires_approval: bool = True


class InvestigateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class InvestigateResponse(BaseModel):
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    revenue_at_risk: float = Field(ge=0)
    recoverable_revenue: float = Field(ge=0)
    recommendations: list[StructuredDecision] = Field(default_factory=list)


class InvestigationRead(InvestigateResponse):
    """Phase 8 audit-trail support (spec: "easily-demonstrable audit trail"
    -- "what AI saw -> concluded -> recommended"): the same
    `InvestigateResponse` a `POST /api/ai/investigate` call returns, plus
    the record's id/question/timestamp/context so past investigations can
    be listed and reviewed later -- see `app.models.ai_investigation` and
    `GET /api/ai/investigations`."""

    id: uuid.UUID
    question: str
    tools_used: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    max_confidence: float = Field(ge=0, le=1)
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedInvestigations(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[InvestigationRead]


class LLMNarrative(BaseModel):
    """What we actually ask the LLM to produce: prose only, no numbers it
    invents itself. `revenue_recovery_agent.py` merges this with
    backend-computed figures to build the final Finding/StructuredDecision/
    InvestigateResponse objects -- so even a full hallucination here can
    only corrupt text fields, never a dollar figure."""

    summary: str
    root_cause_narratives: list[str] = Field(default_factory=list)
    recommendation_reasons: list[str] = Field(default_factory=list)
