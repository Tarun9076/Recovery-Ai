from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_session
from app.schemas.dashboard import DashboardSummary
from app.services.dashboard import get_dashboard_summary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(session: Session = Depends(get_session)) -> DashboardSummary:
    return get_dashboard_summary(session)
