from pydantic import BaseModel


class FailureTrendPoint(BaseModel):
    date: str
    total_payments: int
    failed_payments: int
    failure_rate: float


class FailureCategoryBreakdown(BaseModel):
    failure_category: str
    count: int


class DashboardSummary(BaseModel):
    total_payments: int
    successful_payments: int
    failed_payments: int
    total_transaction_value: float
    failed_transaction_value: float
    failure_rate: float
    total_merchants: int
    total_customers: int
    total_orders: int
    failure_trend: list[FailureTrendPoint]
    failure_category_breakdown: list[FailureCategoryBreakdown]
