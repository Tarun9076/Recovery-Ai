from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session

from app.api.deps import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    session.exec(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
