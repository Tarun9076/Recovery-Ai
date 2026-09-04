import uuid

from pydantic import BaseModel


class SimulatePaymentRequest(BaseModel):
    recovery_action_id: uuid.UUID
    amount: float | None = None
