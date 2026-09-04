import uuid
from datetime import datetime

from pydantic import BaseModel


class CustomerRead(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID

    name: str
    email: str
    phone: str

    customer_since: datetime
    lifetime_value: float
    order_count: int
    successful_payment_count: int
    failed_payment_count: int

    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedCustomers(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CustomerRead]
