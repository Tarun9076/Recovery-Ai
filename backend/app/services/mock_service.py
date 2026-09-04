"""Mock payment simulation (spec section 8): "customer payment -> webhook ->
verification -> database update." Only available when RAZORPAY_MODE=mock.

This does not shortcut the pipeline -- it builds a `payment_link.paid`
payload shaped exactly like a real Razorpay webhook, self-signs it with a
fixed mock secret, and feeds it through the *exact same*
`process_razorpay_webhook` that a real delivery goes through (signature
verification included). The only thing "mocked" is who sent the request;
every response is stamped `simulated: true` so it can never be confused
with a genuine Razorpay confirmation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

from sqlmodel import Session

from app.core.config import get_settings
from app.models.enums import RecoveryActionStatus
from app.models.payment import Payment
from app.models.recovery_action import RecoveryAction
from app.services.webhook_service import process_razorpay_webhook

MOCK_WEBHOOK_SECRET = "mock_simulated_webhook_secret"


class SimulationNotAllowedError(ValueError):
    pass


class SimulationNotFoundError(ValueError):
    pass


class SimulationStateError(ValueError):
    pass


def simulate_payment(session: Session, recovery_action_id: uuid.UUID, amount: float | None = None) -> dict:
    settings = get_settings()
    if settings.razorpay_mode != "mock":
        raise SimulationNotAllowedError(
            "Payment simulation is only available when RAZORPAY_MODE=mock. "
            "In test mode, pay the real Razorpay test-mode payment link instead."
        )

    action = session.get(RecoveryAction, recovery_action_id)
    if action is None:
        raise SimulationNotFoundError(f"No recovery action {recovery_action_id}.")
    if action.status != RecoveryActionStatus.EXECUTED:
        raise SimulationStateError(
            f"Recovery action is {action.status.value}, not EXECUTED -- only an action with an "
            f"active payment link can have a payment simulated against it."
        )

    payment_link_id = (action.provider_response or {}).get("payment_link_id")
    if not payment_link_id:
        raise SimulationStateError("This recovery action has no payment_link_id in its provider response.")

    payment = session.get(Payment, action.payment_id)
    amount_to_simulate = amount if amount is not None else payment.amount
    amount_paid_paise = round(amount_to_simulate * 100)

    event_id = f"mock_evt_{uuid.uuid4().hex}"
    body = json.dumps({
        "entity": "event",
        "event": "payment_link.paid",
        "contains": ["payment_link"],
        "payload": {
            "payment_link": {
                "entity": {"id": payment_link_id, "amount_paid": amount_paid_paise, "status": "paid"}
            }
        },
        "created_at": int(datetime.now(timezone.utc).timestamp()),
    })
    signature = hmac.new(MOCK_WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()

    result = process_razorpay_webhook(session, body, signature, event_id=event_id, secret=MOCK_WEBHOOK_SECRET)
    result["simulated"] = True
    return result
