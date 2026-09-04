import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class AIInvestigation(SQLModel, table=True):
    """Audit record for one `POST /api/ai/investigate` run. Stores what was
    asked, which tools/data sources were touched, and the full findings and
    recommendations produced -- no secrets or credentials ever pass through
    this pipeline, so there's nothing sensitive to redact here."""

    __tablename__ = "ai_investigations"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    question: str
    tools_used: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    data_sources: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    findings: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    recommendations: list[dict] = Field(default_factory=list, sa_column=Column(JSON))

    summary: str
    revenue_at_risk: float
    recoverable_revenue: float
    max_confidence: float

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
