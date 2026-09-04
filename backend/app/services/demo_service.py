"""Phase 8 demo-mode support. Two things a buildathon demo needs that no
earlier phase provided:

1. `reset_demo` -- clears every table the campaign/investigation/webhook
   workflow *writes to* (recovery_actions, recovery_campaigns,
   recovery_opportunities, recovery_predictions, webhook_events,
   audit_logs, ai_investigations) so a demo can be re-run from a clean
   slate. It deliberately never touches merchants/customers/orders/
   payments/payment_failures/merchant_policies -- that's the fixed
   synthetic dataset `scripts/seed_database.py` loaded once, and it is
   what makes Demo Mode deterministic: reset as many times as you like,
   the same known incident is still there afterwards.
2. `simulate_provider_failure` -- runs the exact real create -> approve ->
   execute pipeline (`campaign_service`, no shortcuts) against one real
   failed payment, but swaps in `FailingPaymentProvider` for the execute
   step so it demonstrates the genuine failure path: a FAILED action, a
   real audit trail entry, zero revenue ever recorded as recovered, and
   the payment still eligible for a fresh retry (spec's named scenario:
   "provider timeout -> failed -> retry available").
"""

from __future__ import annotations

import uuid

from sqlmodel import Session, delete, select

from app.models.ai_investigation import AIInvestigation
from app.models.audit_log import AuditLog
from app.models.enums import PaymentStatus, RecoveryActionStatus
from app.models.payment import Payment
from app.models.recovery_action import RecoveryAction
from app.models.recovery_campaign import RecoveryCampaign
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.recovery_prediction import RecoveryPrediction
from app.models.webhook_event import WebhookEvent
from app.services import campaign_service
from app.services.payment_provider import FailingPaymentProvider

MAX_AUTO_SELECT_CANDIDATES = 20


class DemoNotReadyError(RuntimeError):
    pass


def reset_demo(session: Session) -> dict:
    counts = {}
    # Order matters: recovery_actions references campaigns/opportunities.
    for model, key in [
        (RecoveryAction, "recovery_actions"),
        (RecoveryCampaign, "recovery_campaigns"),
        (RecoveryOpportunity, "recovery_opportunities"),
        (RecoveryPrediction, "recovery_predictions"),
        (WebhookEvent, "webhook_events"),
        (AuditLog, "audit_logs"),
        (AIInvestigation, "ai_investigations"),
    ]:
        result = session.exec(delete(model))
        counts[key] = result.rowcount or 0
    session.commit()
    return counts


def _auto_select_candidate_payment_ids(session: Session) -> list[uuid.UUID]:
    """Highest-amount failed payments with no active (non-FAILED) recovery
    action -- the same "already in flight or done" definition
    `campaign_service._has_active_recovery_action` uses. Ranked by amount
    only (no prediction lookup needed here): `create_campaign` itself runs
    the real prediction/policy check per candidate, so this just needs to
    offer plausible candidates, not pre-filter by probability."""
    has_active_action = (
        select(RecoveryAction.id)
        .where(RecoveryAction.payment_id == Payment.id, RecoveryAction.status != RecoveryActionStatus.FAILED)
        .exists()
    )
    rows = session.exec(
        select(Payment.id)
        .where(Payment.status == PaymentStatus.failed, ~has_active_action)
        .order_by(Payment.amount.desc())
        .limit(MAX_AUTO_SELECT_CANDIDATES)
    ).all()
    return list(rows)


def simulate_provider_failure(
    session: Session, *, payment_id: uuid.UUID | None = None, created_by: str = "demo",
) -> RecoveryCampaign:
    candidates = [payment_id] if payment_id is not None else _auto_select_candidate_payment_ids(session)
    if not candidates:
        raise DemoNotReadyError(
            "No eligible failed payment available to simulate a provider failure against."
        )

    last_error: campaign_service.CampaignValidationError | None = None
    campaign = None
    for candidate_id in candidates:
        try:
            campaign, _excluded = campaign_service.create_campaign(
                session, name="Demo: Simulated Provider Failure",
                payment_ids=[candidate_id], created_by=created_by,
            )
            break
        except campaign_service.CampaignValidationError as exc:
            last_error = exc
            continue

    if campaign is None:
        raise DemoNotReadyError(
            str(last_error) if last_error else "No candidate payment qualified for a recovery campaign."
        )

    campaign_service.approve_campaign(session, campaign.id, approved_by=created_by, auto_execute=False)
    return campaign_service.execute_campaign(session, campaign.id, provider=FailingPaymentProvider())
