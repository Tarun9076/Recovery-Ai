from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.revenue_recovery_agent import RevenueRecoveryAgent
from app.agents.schemas import (
    InvestigateRequest,
    InvestigateResponse,
    InvestigationRead,
    PaginatedInvestigations,
)
from app.api.deps import get_session
from app.models.ai_investigation import AIInvestigation

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/investigate", response_model=InvestigateResponse)
def investigate(
    request: InvestigateRequest,
    session: Session = Depends(get_session),
    llm_client: LLMClient = Depends(get_llm_client),
) -> InvestigateResponse:
    agent = RevenueRecoveryAgent(session, llm_client=llm_client)
    response = agent.investigate(request.question)

    max_confidence = max((r.confidence for r in response.recommendations), default=0.0)
    session.add(AIInvestigation(
        question=request.question,
        tools_used=agent.last_tools_used,
        data_sources=agent.last_data_sources,
        findings=[f.model_dump(mode="json") for f in response.findings],
        recommendations=[r.model_dump(mode="json") for r in response.recommendations],
        summary=response.summary,
        revenue_at_risk=response.revenue_at_risk,
        recoverable_revenue=response.recoverable_revenue,
        max_confidence=max_confidence,
    ))
    session.commit()

    return response


@router.get("/investigations", response_model=PaginatedInvestigations)
def list_investigations(
    session: Session = Depends(get_session),
    limit: int = Query(default=20, le=100, gt=0),
    offset: int = Query(default=0, ge=0),
) -> PaginatedInvestigations:
    """Phase 8 audit-trail support: past investigation runs, most recent
    first -- each one already the exact same real, LLM-narrated output
    `POST /investigate` returned at the time, never regenerated."""
    total = session.exec(select(func.count()).select_from(AIInvestigation)).one()
    rows = session.exec(
        select(AIInvestigation).order_by(AIInvestigation.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return PaginatedInvestigations(
        total=total, limit=limit, offset=offset,
        items=[InvestigationRead.model_validate(r) for r in rows],
    )
