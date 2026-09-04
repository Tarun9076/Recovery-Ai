"""Campaign lifecycle: create -> approve -> (mock) execute, or reject.
Every number here is computed fresh from the database and the ML/policy
engines -- nothing from a client request is ever trusted as-is beyond
"which payment_ids were selected" (spec section 4: "Never trust frontend
calculations").
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.customer import Customer
from app.models.enums import (
    AuditEventType,
    CampaignStatus,
    OpportunityStatus,
    PaymentStatus,
    RecoveryActionStatus,
)
from app.models.merchant import Merchant
from app.models.merchant_policy import MerchantPolicy
from app.models.payment import Payment
from app.models.payment_failure import PaymentFailure
from app.models.recovery_action import RecoveryAction
from app.models.recovery_campaign import RecoveryCampaign
from app.models.recovery_opportunity import RecoveryOpportunity
from app.services import recovery_predictor
from app.services.action_selector import (
    EXECUTABLE_ACTIONS,
    ActionDecision,
    CategorySpikeMap,
    RecoveryActionSelector,
    compute_category_spike_map,
)
from app.services.audit import write_audit_log
from app.services.payment_provider import PaymentProvider, get_payment_provider
from app.services.policy_engine import PolicyEngine


class OpportunityValidationError(ValueError):
    pass


class CampaignValidationError(ValueError):
    pass


class CampaignNotFoundError(ValueError):
    pass


class CampaignStateError(ValueError):
    pass


def get_or_refresh_opportunity(
    session: Session, payment_id: uuid.UUID, *, spike_map: CategorySpikeMap | None = None,
) -> tuple[RecoveryOpportunity, ActionDecision]:
    """Recomputes a payment's recovery prediction AND its recommended action
    from scratch and upserts `recovery_opportunities` -- never reads a
    possibly-stale cached probability/action from the request.

    The action recommendation is delegated entirely to
    `RecoveryActionSelector` (spec: ML predicts *whether* a payment is
    recoverable, a separate policy layer decides *what to do about it* --
    see action_selector.py's module docstring for the bug this fixes).
    `create_campaign` (the only caller that processes more than one payment
    per call) computes `spike_map` once and passes it in; a single on-demand
    refresh computes it fresh here (two cheap aggregate queries, not a
    per-payment cost -- see compute_category_spike_map's docstring)."""
    payment = session.get(Payment, payment_id)
    if payment is None or payment.status != PaymentStatus.failed:
        raise OpportunityValidationError(f"{payment_id} is not a failed payment.")

    prediction = recovery_predictor.predict_recovery(payment_id, session)
    probability = prediction["recovery_probability"]
    expected_recovery = prediction["expected_recovery"]
    confidence = prediction["confidence"]

    failure = session.exec(select(PaymentFailure).where(PaymentFailure.payment_id == payment_id)).first()
    policy = session.exec(select(MerchantPolicy)).first()
    if spike_map is None:
        spike_map = compute_category_spike_map(session)

    selector = RecoveryActionSelector(session)
    decision = selector.select(
        payment=payment, failure=failure, recovery_probability=probability,
        expected_recovery=expected_recovery, confidence=confidence, policy=policy, spike_map=spike_map,
    )

    existing = session.exec(
        select(RecoveryOpportunity).where(RecoveryOpportunity.payment_id == payment_id)
    ).first()

    if existing is not None:
        existing.recovery_probability = probability
        existing.expected_recovery = expected_recovery
        existing.recommended_action = decision.action
        existing.reason = decision.reason
        existing.confidence = confidence
        existing.updated_at = datetime.now(timezone.utc)
        session.add(existing)
        opportunity = existing
    else:
        opportunity = RecoveryOpportunity(
            payment_id=payment_id, customer_id=payment.customer_id,
            recovery_probability=probability, expected_recovery=expected_recovery,
            recommended_action=decision.action, reason=decision.reason, confidence=confidence,
        )
        session.add(opportunity)

    session.commit()
    session.refresh(opportunity)
    return opportunity, decision


def _has_active_recovery_action(session: Session, payment_id: uuid.UUID) -> bool:
    """Idempotency guard (spec section 7): a payment with a recovery action
    that's PENDING, AUTHORIZED, or EXECUTED already has one in flight or
    completed -- it must not be selected into a second campaign. Only a
    payment whose *only* prior action(s) are FAILED may be retried (a new
    action created for it), since nothing was actually delivered."""
    existing = session.exec(
        select(RecoveryAction).where(
            RecoveryAction.payment_id == payment_id,
            RecoveryAction.status != RecoveryActionStatus.FAILED,
        )
    ).first()
    return existing is not None


def _cap_by_customer_within_batch(
    included: list[tuple[RecoveryOpportunity, ActionDecision]], max_contacts: int,
) -> tuple[list[tuple[RecoveryOpportunity, ActionDecision]], list[dict]]:
    """A per-opportunity contact-limit check only sees *prior* campaigns --
    it can't see siblings being selected into this same new campaign. This
    catches that: within one campaign, no customer gets more than
    max_customer_contacts opportunities, keeping the highest-expected-value
    ones and excluding the rest."""
    ordered = sorted(included, key=lambda pair: pair[0].expected_recovery, reverse=True)
    seen: dict[uuid.UUID, int] = {}
    kept, excluded = [], []
    for opportunity, decision in ordered:
        count = seen.get(opportunity.customer_id, 0)
        if count >= max_contacts:
            excluded.append({
                "payment_id": str(opportunity.payment_id),
                "reason": f"Exceeds max_customer_contacts={max_contacts} within this campaign.",
            })
            continue
        seen[opportunity.customer_id] = count + 1
        kept.append((opportunity, decision))
    return kept, excluded


def create_campaign(
    session: Session, *, name: str, payment_ids: list[uuid.UUID], created_by: str,
) -> tuple[RecoveryCampaign, list[dict]]:
    merchant = session.exec(select(Merchant)).first()
    if merchant is None:
        raise CampaignValidationError("No merchant configured.")
    policy = session.exec(select(MerchantPolicy)).first()
    engine = PolicyEngine(session)
    # Computed once for the whole batch, not once per payment -- see
    # compute_category_spike_map's docstring for why a per-payment version
    # of this would be an N+1 query pattern.
    spike_map = compute_category_spike_map(session)

    included: list[tuple[RecoveryOpportunity, ActionDecision]] = []
    excluded: list[dict] = []

    for payment_id in payment_ids:
        if _has_active_recovery_action(session, payment_id):
            excluded.append({
                "payment_id": str(payment_id),
                "reason": "A recovery action for this payment is already pending, authorized, or executed.",
            })
            continue

        try:
            opportunity, decision = get_or_refresh_opportunity(session, payment_id, spike_map=spike_map)
        except OpportunityValidationError as exc:
            excluded.append({"payment_id": str(payment_id), "reason": str(exc)})
            continue

        # Only an action the current provider abstraction can actually
        # execute (today: PAYMENT_LINK only -- see action_selector.py's
        # EXECUTABLE_ACTIONS) may become a real, executable campaign line
        # item. A payment recommended ALTERNATIVE_PAYMENT_METHOD,
        # REQUEST_CUSTOMER_CORRECTION, DEFER, RETRY, NO_ACTION, or
        # MANUAL_REVIEW is reported back as excluded, with the action
        # decision's own reason -- never silently defaulted to a payment
        # link. This is the fix for the reported bug: previously *any*
        # qualifying payment (regardless of the recommended action) was
        # included and executed as a payment link.
        if decision.executable:
            included.append((opportunity, decision))
        else:
            excluded.append({
                "payment_id": str(payment_id),
                "reason": f"Recommended action is {decision.action.value}, not currently executable: {decision.reason}",
            })

    max_contacts = policy.max_customer_contacts if policy else 1
    included, capped_out = _cap_by_customer_within_batch(included, max_contacts)
    excluded += capped_out

    if not included:
        raise CampaignValidationError("No selected opportunities passed policy validation.")

    total_amount = sum(o.payment.amount for o, _ in included)
    expected_recovery = sum(o.expected_recovery for o, _ in included)

    limit_check = engine.check_campaign_limit(total_amount, policy)
    if not limit_check.passed:
        raise CampaignValidationError(limit_check.reason)

    campaign = RecoveryCampaign(
        merchant_id=merchant.id, name=name, target_count=len(included),
        total_amount=total_amount, expected_recovery=expected_recovery,
        created_by=created_by, status=CampaignStatus.PENDING_APPROVAL,
    )
    session.add(campaign)
    session.flush()

    for opportunity, _decision in included:
        opportunity.status = OpportunityStatus.REVIEWED
        opportunity.updated_at = datetime.now(timezone.utc)
        session.add(opportunity)
        session.add(RecoveryAction(
            campaign_id=campaign.id, opportunity_id=opportunity.id,
            payment_id=opportunity.payment_id, customer_id=opportunity.customer_id,
            action_type=opportunity.recommended_action, status=RecoveryActionStatus.PENDING,
        ))

    write_audit_log(
        session, AuditEventType.CAMPAIGN_CREATED, actor=created_by,
        entity_type="campaign", entity_id=campaign.id,
        details={"target_count": len(included), "excluded_count": len(excluded), "total_amount": total_amount},
    )
    write_audit_log(
        session, AuditEventType.POLICY_CHECKED, actor="system",
        entity_type="campaign", entity_id=campaign.id,
        details={"campaign_limit_check": limit_check.as_dict(), "included": len(included), "excluded": excluded},
    )

    session.commit()
    session.refresh(campaign)
    return campaign, excluded


def approve_campaign(
    session: Session, campaign_id: uuid.UUID, *, approved_by: str,
    provider: PaymentProvider | None = None, auto_execute: bool = True,
) -> RecoveryCampaign:
    """`auto_execute=True` (the default, and what every pre-Phase-8 caller
    relies on) approves and immediately executes in one call, exactly as
    Phase 4 always behaved. The API layer (Phase 8) instead calls this with
    `auto_execute=False` and a separate `execute_campaign()` call, so
    "Approve" and "Execute" are genuinely distinct actions in the demo
    control panel and the merchant-facing workflow -- approval no longer
    silently sends anything."""
    campaign = session.get(RecoveryCampaign, campaign_id)
    if campaign is None:
        raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
    if campaign.status != CampaignStatus.PENDING_APPROVAL:
        raise CampaignStateError(f"Campaign is {campaign.status.value}; only a PENDING_APPROVAL campaign can be approved.")

    policy = session.exec(select(MerchantPolicy)).first()
    engine = PolicyEngine(session)
    limit_check = engine.check_campaign_limit(campaign.total_amount, policy)
    action_check = engine.check_allowed_action(policy)
    write_audit_log(
        session, AuditEventType.POLICY_CHECKED, actor="system",
        entity_type="campaign", entity_id=campaign.id,
        details={"stage": "approval", "checks": [limit_check.as_dict(), action_check.as_dict()]},
    )
    if not (limit_check.passed and action_check.passed):
        session.commit()
        raise CampaignValidationError(
            "Campaign no longer satisfies merchant policy: "
            + "; ".join(c.reason for c in (limit_check, action_check) if not c.passed)
        )

    campaign.approved_by = approved_by
    campaign.approved_at = datetime.now(timezone.utc)
    campaign.status = CampaignStatus.APPROVED
    session.add(campaign)
    write_audit_log(
        session, AuditEventType.CAMPAIGN_APPROVED, actor=approved_by,
        entity_type="campaign", entity_id=campaign.id, details={},
    )
    session.commit()

    if auto_execute:
        return execute_campaign(session, campaign_id, provider=provider)

    session.refresh(campaign)
    return campaign


def execute_campaign(
    session: Session, campaign_id: uuid.UUID, *, provider: PaymentProvider | None = None,
) -> RecoveryCampaign:
    """The separate "Execute Campaign" step: only valid on an APPROVED
    campaign (enforced both here and by `_execute_campaign`'s own
    `check_approval` call -- spec: "No campaign executes without approval").
    Safe to call once; a second call raises `CampaignStateError` since the
    campaign is no longer APPROVED (it's RUNNING/COMPLETED/FAILED) -- see
    test_campaigns_api.py::test_execute_twice_returns_409."""
    campaign = session.get(RecoveryCampaign, campaign_id)
    if campaign is None:
        raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
    if campaign.status != CampaignStatus.APPROVED:
        raise CampaignStateError(f"Campaign is {campaign.status.value}; only an APPROVED campaign can be executed.")

    _execute_campaign(session, campaign, provider=provider or get_payment_provider())

    session.refresh(campaign)
    return campaign


def reject_campaign(session: Session, campaign_id: uuid.UUID, *, rejected_by: str, reason: str) -> RecoveryCampaign:
    campaign = session.get(RecoveryCampaign, campaign_id)
    if campaign is None:
        raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
    if campaign.status != CampaignStatus.PENDING_APPROVAL:
        raise CampaignStateError(f"Campaign is {campaign.status.value}; only a PENDING_APPROVAL campaign can be rejected.")

    campaign.status = CampaignStatus.CANCELLED
    campaign.rejection_reason = reason
    session.add(campaign)

    actions = session.exec(select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)).all()
    for action in actions:
        # These never ran and now never will -- FAILED (not a fresh
        # PENDING) so they read correctly later and, importantly, don't
        # count toward check_customer_contact_limit (which only counts
        # EXECUTED actions as an actual contact).
        action.status = RecoveryActionStatus.FAILED
        session.add(action)

        opportunity = session.get(RecoveryOpportunity, action.opportunity_id)
        if opportunity is not None:
            opportunity.status = OpportunityStatus.REJECTED
            opportunity.updated_at = datetime.now(timezone.utc)
            session.add(opportunity)

    write_audit_log(
        session, AuditEventType.CAMPAIGN_REJECTED, actor=rejected_by,
        entity_type="campaign", entity_id=campaign.id, details={"reason": reason},
    )
    session.commit()
    session.refresh(campaign)
    return campaign


def _execute_campaign(session: Session, campaign: RecoveryCampaign, *, provider: PaymentProvider) -> None:
    """Creates a recovery link per action via `provider` (mock or real
    Razorpay test-mode, per RAZORPAY_MODE -- see get_payment_provider). A
    successful link is recorded as EXECUTED -- this function never sets an
    opportunity or action to RECOVERED, because a created link is not a
    payment confirmation (spec section 11). The only path that may ever
    record a real recovery is a verified inbound webhook -- see
    `app/api/webhooks.py`."""
    engine = PolicyEngine(session)
    approval_check = engine.check_approval(campaign)
    if not approval_check.passed:
        raise CampaignStateError(approval_check.reason)

    campaign.status = CampaignStatus.RUNNING
    session.add(campaign)
    session.commit()

    actions = session.exec(select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)).all()

    provider_name = type(provider).__name__

    for action in actions:
        action.status = RecoveryActionStatus.AUTHORIZED
        action.authorized_at = datetime.now(timezone.utc)
        session.add(action)
        write_audit_log(
            session, AuditEventType.RECOVERY_ACTION_AUTHORIZED, actor="system",
            entity_type="recovery_action", entity_id=action.id,
            details={
                "provider": provider_name, "payment_id": str(action.payment_id),
                "action_type": action.action_type.value,
            },
        )
        session.commit()

        payment = session.get(Payment, action.payment_id)
        customer = session.get(Customer, action.customer_id)
        opportunity = session.get(RecoveryOpportunity, action.opportunity_id)

        # Final eligibility gate (spec: "the frontend must never be able to
        # bypass this"): `create_campaign` only ever includes an executable
        # action (see EXECUTABLE_ACTIONS), so this should be unreachable in
        # practice -- but it's the last backend checkpoint before a
        # financial action fires, so it revalidates rather than trusting
        # that upstream invariant. A non-executable action_type fails
        # closed as FAILED, exactly like a real provider error, instead of
        # ever calling the provider for an action it was never eligible for.
        if action.action_type not in EXECUTABLE_ACTIONS:
            response = {
                "success": False,
                "error": f"Action type {action.action_type.value} is not executable by the current payment provider.",
                "error_type": "ActionNotExecutable",
            }
        else:
            try:
                response = provider.create_recovery_link(
                    payment_id=action.payment_id, amount=payment.amount, currency=payment.currency,
                    customer_name=customer.name, customer_email=customer.email, customer_contact=customer.phone,
                    reference_id=str(action.id),
                )
            except Exception as exc:  # provider failure -- record and move on, never crash the whole campaign
                response = {"success": False, "error": str(exc), "error_type": type(exc).__name__}

        action.provider_response = response
        action.payment_link_id = response.get("payment_link_id")
        action.status = RecoveryActionStatus.EXECUTED if response.get("success") else RecoveryActionStatus.FAILED
        action.executed_at = datetime.now(timezone.utc)
        session.add(action)

        if opportunity is not None:
            opportunity.status = (
                OpportunityStatus.EXECUTED if response.get("success") else OpportunityStatus.FAILED
            )
            opportunity.updated_at = datetime.now(timezone.utc)
            session.add(opportunity)

        write_audit_log(
            session, AuditEventType.RECOVERY_ACTION_EXECUTED, actor="system",
            entity_type="recovery_action", entity_id=action.id,
            details={
                "provider": provider_name,
                "request_type": "create_payment_link",
                "payment_id": str(action.payment_id),
                "opportunity_id": str(action.opportunity_id),
                "execution_status": action.status.value,
                "provider_response_id": response.get("payment_link_id"),
                "error": response.get("error"),
            },
        )
        session.commit()

    refreshed_actions = session.exec(select(RecoveryAction).where(RecoveryAction.campaign_id == campaign.id)).all()
    all_failed = all(a.status == RecoveryActionStatus.FAILED for a in refreshed_actions)
    campaign.status = CampaignStatus.FAILED if all_failed else CampaignStatus.COMPLETED
    campaign.completed_at = datetime.now(timezone.utc)
    session.add(campaign)
    session.commit()
