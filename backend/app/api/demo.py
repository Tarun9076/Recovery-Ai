from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.campaigns import _campaign_detail
from app.api.deps import get_session
from app.core.config import get_settings
from app.schemas.campaign import CampaignDetailRead
from app.schemas.demo import DemoResetResponse, SimulateProviderFailureRequest
from app.services.demo_service import DemoNotReadyError, reset_demo, simulate_provider_failure

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/reset", response_model=DemoResetResponse)
def reset(session: Session = Depends(get_session)) -> DemoResetResponse:
    """Clears every campaign/investigation/webhook workflow table so the
    demo can be replayed from a clean slate -- see demo_service.reset_demo
    for exactly what is and isn't touched (the underlying synthetic
    dataset never is, which is what keeps Demo Mode deterministic)."""
    counts = reset_demo(session)
    return DemoResetResponse(**counts)


@router.post("/simulate-provider-failure", response_model=CampaignDetailRead)
def simulate_provider_failure_endpoint(
    request: SimulateProviderFailureRequest, session: Session = Depends(get_session),
) -> CampaignDetailRead:
    """DEMO ONLY (spec section 4): runs a real campaign through create ->
    approve -> execute, forcing the execute step to fail exactly like a
    provider timeout would. Gated to RAZORPAY_MODE=mock for the same
    reason app/api/mock.py's simulate-payment is: it's a controlled demo
    mechanism, not something to run against a real Razorpay integration."""
    settings = get_settings()
    if settings.razorpay_mode != "mock":
        raise HTTPException(
            status_code=403,
            detail="Provider-failure simulation is only available when RAZORPAY_MODE=mock.",
        )

    try:
        campaign = simulate_provider_failure(
            session, payment_id=request.payment_id, created_by=request.created_by,
        )
    except DemoNotReadyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _campaign_detail(session, campaign)
