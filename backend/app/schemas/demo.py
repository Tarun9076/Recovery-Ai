import uuid

from pydantic import BaseModel, Field


class DemoResetResponse(BaseModel):
    """Row counts actually deleted from each workflow table -- so "Reset
    Demo" is verifiably not a no-op, without exposing the deleted rows
    themselves."""

    recovery_actions: int
    recovery_campaigns: int
    recovery_opportunities: int
    recovery_predictions: int
    webhook_events: int
    audit_logs: int
    ai_investigations: int


class SimulateProviderFailureRequest(BaseModel):
    payment_id: uuid.UUID | None = None
    created_by: str = Field(default="demo", min_length=1, max_length=200)
