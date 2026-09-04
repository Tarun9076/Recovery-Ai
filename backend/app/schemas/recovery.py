import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import RecoverySegment


class RecoveryFactor(BaseModel):
    factor: str
    direction: str
    shap_value: float


class RecoveryPredictionRead(BaseModel):
    payment_id: uuid.UUID
    recovery_probability: float
    expected_recovery: float
    confidence: float
    segment: RecoverySegment
    top_factors: list[RecoveryFactor]

    model_name: str
    model_version: str
    feature_version: str
    training_timestamp: datetime
    predicted_at: datetime

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class RecoveryOpportunityRead(RecoveryPredictionRead):
    """A prediction plus enough payment/failure context to act on it without
    a second round trip."""

    amount: float
    currency: str
    customer_id: uuid.UUID
    payment_method: str
    failure_category: str | None = None
    recommended_action: str | None = None
    reason: str | None = None
    created_at: datetime


class PaginatedRecoveryOpportunities(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[RecoveryOpportunityRead]


class RecoveryMetricsRead(BaseModel):
    """Spec section 7. `revenue_recovered` reflects only verified webhook
    confirmations (see webhook_service.py) -- never `expected_recovery`."""

    revenue_at_risk: float
    recoverable_revenue: float
    revenue_recovered: float
    recovery_rate: float


class AnalyzeResponse(BaseModel):
    analyzed_count: int
    high_recovery_count: int
    medium_recovery_count: int
    low_recovery_count: int
    total_expected_recovery: float
    model_name: str
    model_version: str
    feature_version: str
    training_timestamp: datetime | None = None

    model_config = {"protected_namespaces": ()}
