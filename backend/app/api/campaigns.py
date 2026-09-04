import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models.audit_log import AuditLog
from app.models.recovery_action import RecoveryAction
from app.models.recovery_campaign import RecoveryCampaign
from app.models.recovery_opportunity import RecoveryOpportunity
from app.schemas.campaign import (
    AuditLogRead,
    CampaignApproveRequest,
    CampaignCreateRequest,
    CampaignCreateResponse,
    CampaignDetailRead,
    CampaignRead,
    CampaignRejectRequest,
    OpportunitySummary,
    PaginatedCampaigns,
    RecoveryActionRead,
)
from app.services.campaign_service import (
    CampaignNotFoundError,
    CampaignStateError,
    CampaignValidationError,
    approve_campaign,
    create_campaign,
    execute_campaign,
    reject_campaign,
)
from app.services.metrics_service import compute_campaign_metrics

router = APIRouter(prefix="/api/recovery/campaigns", tags=["campaigns"])


def _campaign_detail(session: Session, campaign: RecoveryCampaign) -> CampaignDetailRead:
    actions = session.exec(
        select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)
    ).all()
    opportunity_ids = [a.opportunity_id for a in actions]
    opportunities = {
        o.id: o for o in session.exec(
            select(RecoveryOpportunity).where(RecoveryOpportunity.id.in_(opportunity_ids))
        ).all()
    } if opportunity_ids else {}

    recommendations = [
        OpportunitySummary(
            payment_id=o.payment_id, customer_id=o.customer_id,
            recovery_probability=o.recovery_probability, expected_recovery=o.expected_recovery,
            recommended_action=o.recommended_action, reason=o.reason, confidence=o.confidence,
            status=o.status,
        )
        for o in (opportunities.get(a.opportunity_id) for a in actions) if o is not None
    ]

    metrics = compute_campaign_metrics(session, campaign)

    # Every event this campaign, its actions, or its opportunities ever
    # wrote (see write_audit_log calls throughout campaign_service.py and
    # webhook_service.py) -- chronological, so the frontend can render
    # "AI concluded -> merchant approved -> system executed -> what
    # actually happened" as a single timeline (spec section 1).
    related_entity_ids = [campaign.id, *(a.id for a in actions), *opportunities.keys()]
    audit_rows = session.exec(
        select(AuditLog).where(AuditLog.entity_id.in_(related_entity_ids)).order_by(AuditLog.created_at.asc())
    ).all()

    return CampaignDetailRead(
        **CampaignRead.model_validate(campaign).model_dump(),
        recommendations=recommendations,
        actions=[RecoveryActionRead.model_validate(a) for a in actions],
        audit_trail=[AuditLogRead.model_validate(a) for a in audit_rows],
        **metrics.as_dict(),
    )


@router.post("", response_model=CampaignCreateResponse)
def create(request: CampaignCreateRequest, session: Session = Depends(get_session)) -> CampaignCreateResponse:
    try:
        campaign, excluded = create_campaign(
            session, name=request.name, payment_ids=request.payment_ids, created_by=request.created_by,
        )
    except CampaignValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return CampaignCreateResponse(campaign=CampaignRead.model_validate(campaign), excluded=excluded)


@router.get("", response_model=PaginatedCampaigns)
def list_campaigns(
    session: Session = Depends(get_session), limit: int = 50, offset: int = 0,
) -> PaginatedCampaigns:
    total = session.exec(select(func.count()).select_from(RecoveryCampaign)).one()
    rows = session.exec(
        select(RecoveryCampaign).order_by(RecoveryCampaign.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return PaginatedCampaigns(
        total=total, limit=limit, offset=offset,
        items=[CampaignRead.model_validate(c) for c in rows],
    )


@router.get("/{campaign_id}", response_model=CampaignDetailRead)
def get_campaign(campaign_id: uuid.UUID, session: Session = Depends(get_session)) -> CampaignDetailRead:
    campaign = session.get(RecoveryCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _campaign_detail(session, campaign)


@router.post("/{campaign_id}/approve", response_model=CampaignDetailRead)
def approve(
    campaign_id: uuid.UUID, request: CampaignApproveRequest, session: Session = Depends(get_session),
) -> CampaignDetailRead:
    """Approval alone -- does NOT execute. Call `POST .../execute`
    separately (spec: distinct "Approve Campaign" / "Execute Campaign"
    demo-panel actions; also the safer real-world pattern of separating
    authorization from execution)."""
    try:
        campaign = approve_campaign(session, campaign_id, approved_by=request.approved_by, auto_execute=False)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (CampaignStateError, CampaignValidationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _campaign_detail(session, campaign)


@router.post("/{campaign_id}/execute", response_model=CampaignDetailRead)
def execute(campaign_id: uuid.UUID, session: Session = Depends(get_session)) -> CampaignDetailRead:
    """Only valid on an APPROVED campaign -- "No campaign executes without
    approval" is enforced by `campaign_service.execute_campaign` itself,
    not just by this route existing."""
    try:
        campaign = execute_campaign(session, campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CampaignStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _campaign_detail(session, campaign)


@router.post("/{campaign_id}/reject", response_model=CampaignDetailRead)
def reject(
    campaign_id: uuid.UUID, request: CampaignRejectRequest, session: Session = Depends(get_session),
) -> CampaignDetailRead:
    try:
        campaign = reject_campaign(
            session, campaign_id, rejected_by=request.rejected_by, reason=request.reason,
        )
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CampaignStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _campaign_detail(session, campaign)
