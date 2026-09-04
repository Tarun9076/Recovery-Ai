"""Processes inbound Razorpay webhooks -- the *only* code path in this
entire codebase that may ever mark a `RecoveryAction`/`RecoveryOpportunity`
RECOVERED or set `recovered_amount`. Spec section 11 (Phase 5) / the
Phase 6 rule: "A recovery action is NOT successful until the backend
receives and verifies actual payment success" -- a cryptographically
verified `payment_link.paid` webhook is exactly that, and only that.

## Idempotency (spec section 4)

Every request -- verified or not, acted on or not -- is written to
`webhook_events` keyed by `(provider, event_id)` under a database UNIQUE
constraint, *before* anything else happens. `event_id` is Razorpay's
`x-razorpay-event-id` header when present (their documented dedup key -- see
https://razorpay.com/docs/webhooks/validate-test/); if a request somehow
arrives without it, a hash of the body+signature stands in, so an exact
redelivery still dedups even then.

Storing first, then treating a unique-constraint violation on insert as
"already recorded" rather than a plain "check-then-insert" in Python,
closes the race where two near-simultaneous redeliveries could otherwise
both pass a naive existence check and double-process. A second layer of
defense also lives in `_find_action_by_payment_link_id`: an action already
RECOVERED is recognized and short-circuited even if the event-id layer
were somehow bypassed.

## What "process" means for a verified event

See `_apply_event`: identify the payment (via the payment link id in the
event payload) -> identify its `RecoveryAction` -> mark it RECOVERED with
the *verified* amount (`entity["amount_paid"]`, never `expected_recovery`,
per spec section 6) -> update the linked `RecoveryOpportunity` -> write the
audit log. Nothing here writes to `RecoveryCampaign` -- its
revenue-recovered/recovery-rate are computed on read from its actions'
`recovered_amount` (see `app/services/metrics_service.py`), so there is no
cached campaign total that could ever drift from the underlying actions.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.config import get_settings
from app.integrations.razorpay.exceptions import RazorpayAuthenticationError, RazorpayWebhookSignatureError
from app.integrations.razorpay.webhooks import parse_webhook_payload, verify_webhook_signature
from app.models.enums import AuditEventType, OpportunityStatus, RecoveryActionStatus
from app.models.recovery_action import RecoveryAction
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.webhook_event import WebhookEvent
from app.services.audit import write_audit_log

HANDLED_EVENT = "payment_link.paid"
PROVIDER = "razorpay"


def process_razorpay_webhook(
    session: Session, raw_body: str, signature: str, *, event_id: str | None = None, secret: str | None = None,
) -> dict:
    """`secret` is normally left as None (read from `RAZORPAY_WEBHOOK_SECRET`)
    -- the mock simulator (`mock_service.py`) is the one caller that passes
    an explicit secret, since it self-signs a payload and needs to verify
    against that same value regardless of what's configured."""
    resolved_secret = secret if secret is not None else get_settings().razorpay_webhook_secret
    if not resolved_secret:
        raise RazorpayAuthenticationError("RAZORPAY_WEBHOOK_SECRET is not configured.")

    resolved_event_id = event_id or hashlib.sha256(f"{raw_body}|{signature}".encode()).hexdigest()

    try:
        verify_webhook_signature(raw_body, signature, resolved_secret)
        signature_verified = True
    except RazorpayWebhookSignatureError:
        signature_verified = False

    payload: dict = {}
    event_type = "unknown"
    if signature_verified:
        try:
            payload = parse_webhook_payload(raw_body)
            event_type = payload.get("event", "unknown")
        except Exception:
            payload = {}
            event_type = "unparseable"

    webhook_event = WebhookEvent(
        provider=PROVIDER, event_type=event_type, event_id=resolved_event_id,
        payload=payload, signature_verified=signature_verified, processed=False,
    )
    session.add(webhook_event)
    try:
        session.commit()
    except IntegrityError:
        # (provider, event_id) already exists -- a genuine redelivery (or a
        # race between two near-simultaneous ones). Never double-process.
        session.rollback()
        existing = session.exec(
            select(WebhookEvent).where(WebhookEvent.provider == PROVIDER, WebhookEvent.event_id == resolved_event_id)
        ).first()
        return {
            "status": "already_recorded" if (existing and existing.processed) else "duplicate_unprocessed",
            "webhook_event_id": str(existing.id) if existing else None,
        }
    session.refresh(webhook_event)

    if not signature_verified:
        raise RazorpayWebhookSignatureError("Razorpay Signature Verification Failed")

    result = _apply_event(session, webhook_event, payload)

    webhook_event.processed = True
    webhook_event.processed_at = datetime.now(timezone.utc)
    session.add(webhook_event)
    session.commit()

    return result


def _apply_event(session: Session, webhook_event: WebhookEvent, payload: dict) -> dict:
    if webhook_event.event_type != HANDLED_EVENT:
        return {"status": "ignored", "event": webhook_event.event_type, "webhook_event_id": str(webhook_event.id)}

    entity = payload.get("payload", {}).get("payment_link", {}).get("entity", {})
    payment_link_id = entity.get("id")
    if not payment_link_id:
        return {"status": "ignored", "reason": "payload has no payment_link entity", "webhook_event_id": str(webhook_event.id)}

    action = _find_action_by_payment_link_id(session, payment_link_id)
    if action is None:
        return {
            "status": "ignored", "reason": "no recovery action matches this payment link",
            "webhook_event_id": str(webhook_event.id),
        }

    if action.status == RecoveryActionStatus.RECOVERED:
        return {"status": "already_recorded", "recovery_action_id": str(action.id), "webhook_event_id": str(webhook_event.id)}

    # Verified successful-payment amount only -- never expected_recovery (spec section 6).
    amount_paid = entity.get("amount_paid", 0) / 100.0

    action.status = RecoveryActionStatus.RECOVERED
    action.recovered_at = datetime.now(timezone.utc)
    action.recovered_amount = amount_paid
    session.add(action)

    opportunity = session.get(RecoveryOpportunity, action.opportunity_id)
    if opportunity is not None:
        opportunity.status = OpportunityStatus.RECOVERED
        opportunity.updated_at = datetime.now(timezone.utc)
        session.add(opportunity)

    write_audit_log(
        session, AuditEventType.RECOVERY_CONFIRMED, actor="razorpay",
        entity_type="recovery_action", entity_id=action.id,
        details={
            "payment_link_id": payment_link_id, "amount_paid": amount_paid,
            "event": webhook_event.event_type, "webhook_event_id": str(webhook_event.id),
        },
    )
    session.commit()

    return {"status": "recovered", "recovery_action_id": str(action.id), "amount_paid": amount_paid, "webhook_event_id": str(webhook_event.id)}


def _find_action_by_payment_link_id(session: Session, payment_link_id: str) -> RecoveryAction | None:
    # A single indexed lookup on RecoveryAction.payment_link_id -- not a
    # full-table fetch of every EXECUTED/RECOVERED action filtered in
    # Python (the original implementation, fixed in Phase 8's performance
    # pass; see that column's docstring in app/models/recovery_action.py).
    # Includes RECOVERED, not just EXECUTED: a redelivered webhook for an
    # already-confirmed action must still be found (so the caller can
    # report "already_recorded"), not silently miss it and report "no
    # matching action" as if something were wrong.
    return session.exec(
        select(RecoveryAction).where(
            RecoveryAction.payment_link_id == payment_link_id,
            RecoveryAction.status.in_([RecoveryActionStatus.EXECUTED, RecoveryActionStatus.RECOVERED]),
        )
    ).first()
