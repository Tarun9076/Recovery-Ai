import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models.customer import Customer
from app.schemas.customer import CustomerRead, PaginatedCustomers

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.get("", response_model=PaginatedCustomers)
def list_customers(
    session: Session = Depends(get_session),
    limit: int = Query(default=50, le=500, gt=0),
    offset: int = Query(default=0, ge=0),
) -> PaginatedCustomers:
    total = session.exec(select(func.count()).select_from(Customer)).one()
    items = session.exec(
        select(Customer).order_by(Customer.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return PaginatedCustomers(total=total, limit=limit, offset=offset, items=items)


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(customer_id: uuid.UUID, session: Session = Depends(get_session)) -> CustomerRead:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer
