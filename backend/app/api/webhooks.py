from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlmodel import Session

from app.api.deps import get_session
from app.integrations.razorpay.exceptions import RazorpayAuthenticationError, RazorpayWebhookSignatureError
from app.services.webhook_service import process_razorpay_webhook

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    session: Session = Depends(get_session),
    x_razorpay_signature: str = Header(..., alias="X-Razorpay-Signature"),
    x_razorpay_event_id: str | None = Header(default=None, alias="x-razorpay-event-id"),
) -> dict:
    """Verifies the signature against the *raw* request body before doing
    anything else -- see app/integrations/razorpay/webhooks.py. Every
    request is recorded to `webhook_events` (see webhook_service.py)
    regardless of outcome, keyed by `x-razorpay-event-id` for idempotency."""
    raw_body = (await request.body()).decode("utf-8")

    try:
        return process_razorpay_webhook(session, raw_body, x_razorpay_signature, event_id=x_razorpay_event_id)
    except RazorpayWebhookSignatureError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RazorpayAuthenticationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
