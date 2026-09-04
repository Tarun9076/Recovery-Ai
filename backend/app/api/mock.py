from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import get_session
from app.schemas.mock import SimulatePaymentRequest
from app.services.mock_service import (
    SimulationNotAllowedError,
    SimulationNotFoundError,
    SimulationStateError,
    simulate_payment,
)

router = APIRouter(prefix="/api/mock", tags=["mock"])


@router.post("/simulate-payment")
def simulate_payment_endpoint(request: SimulatePaymentRequest, session: Session = Depends(get_session)) -> dict:
    """DEMO/TEST ONLY: simulates a customer paying a recovery link, driven
    through the real webhook-verification pipeline (see mock_service.py).
    Every response carries `"simulated": true`. Only available when
    RAZORPAY_MODE=mock."""
    try:
        return simulate_payment(session, request.recovery_action_id, amount=request.amount)
    except SimulationNotAllowedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SimulationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SimulationStateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
