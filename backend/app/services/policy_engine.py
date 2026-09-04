"""The single authority for every merchant-policy check in the campaign
workflow. Spec section 8: "No campaign may bypass this service" -- so
`campaign_service.py` never re-implements or shortcuts a threshold check
itself, it always calls into `PolicyEngine`.

Each `check_*` method returns a `PolicyCheckResult` (never raises) so
callers can collect every check's outcome for the audit log's
`policy_checked` event, rather than stopping at the first failure.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlmodel import Session, select

from app.models.enums import CampaignStatus, RecoveryActionStatus
from app.models.merchant_policy import MerchantPolicy
from app.models.recovery_action import RecoveryAction

DEFAULT_MINIMUM_RECOVERY_PROBABILITY = 0.65
DEFAULT_MAX_CUSTOMER_CONTACTS = 1


@dataclass
class PolicyCheckResult:
    check: str
    passed: bool
    reason: str

    def as_dict(self) -> dict:
        return {"check": self.check, "passed": self.passed, "reason": self.reason}


class PolicyEngine:
    def __init__(self, session: Session):
        self.session = session

    # -- individual checks ---------------------------------------------

    def check_recovery_probability(self, probability: float, policy: MerchantPolicy | None) -> PolicyCheckResult:
        threshold = policy.minimum_recovery_probability if policy else DEFAULT_MINIMUM_RECOVERY_PROBABILITY
        passed = probability >= threshold
        reason = (
            f"Recovery probability {probability:.0%} meets the {threshold:.0%} policy threshold."
            if passed else
            f"Recovery probability {probability:.0%} is below the {threshold:.0%} policy threshold."
        )
        return PolicyCheckResult("recovery_probability", passed, reason)

    def check_customer_contact_limit(self, customer_id: uuid.UUID, policy: MerchantPolicy | None) -> PolicyCheckResult:
        """Counts actions that actually reached the customer (status
        EXECUTED -- a link was really created) against
        `max_customer_contacts`. PENDING (sitting in a not-yet-approved
        campaign) and FAILED (link creation failed, or the campaign was
        rejected/cancelled before ever executing) must NOT count -- nothing
        was actually sent, so they shouldn't permanently block the customer
        from a future campaign."""
        max_contacts = policy.max_customer_contacts if policy else DEFAULT_MAX_CUSTOMER_CONTACTS
        existing = self.session.exec(
            select(RecoveryAction).where(
                RecoveryAction.customer_id == customer_id,
                RecoveryAction.status == RecoveryActionStatus.EXECUTED,
            )
        ).all()
        passed = len(existing) < max_contacts
        reason = (
            f"Customer has {len(existing)} prior contact(s), under the limit of {max_contacts}."
            if passed else
            f"Customer already has {len(existing)} contact(s), at or above the limit of {max_contacts}."
        )
        return PolicyCheckResult("customer_contact_limit", passed, reason)

    def check_campaign_limit(self, total_amount: float, policy: MerchantPolicy | None) -> PolicyCheckResult:
        max_amount = policy.max_campaign_amount if policy else None
        if max_amount is None:
            return PolicyCheckResult("campaign_limit", True, "No max_campaign_amount configured -- no cap applies.")
        passed = total_amount <= max_amount
        reason = (
            f"Campaign amount ₹{total_amount:,.2f} is within the ₹{max_amount:,.2f} policy limit."
            if passed else
            f"Campaign amount ₹{total_amount:,.2f} exceeds the ₹{max_amount:,.2f} policy limit."
        )
        return PolicyCheckResult("campaign_limit", passed, reason)

    def check_allowed_action(self, policy: MerchantPolicy | None) -> PolicyCheckResult:
        """`allowed_actions` on the merchant policy names outreach channels
        (email/sms/whatsapp), not action types -- so this checks that at
        least one delivery channel is enabled at all. An empty list means
        the merchant has disabled all outreach, so nothing is deliverable
        regardless of what action type is recommended."""
        allowed = policy.allowed_actions if policy else ["email", "sms", "whatsapp"]
        passed = bool(allowed)
        reason = (
            f"Merchant has {len(allowed)} outreach channel(s) enabled."
            if passed else
            "Merchant policy has no allowed outreach channels configured."
        )
        return PolicyCheckResult("allowed_action", passed, reason)

    def check_approval(self, campaign) -> PolicyCheckResult:
        """Guards execution: a campaign may only proceed to authorization
        once it has actually been approved (spec: "No campaign executes
        without approval")."""
        passed = campaign.status == CampaignStatus.APPROVED and campaign.approved_by is not None
        reason = (
            f"Campaign approved by {campaign.approved_by}."
            if passed else
            f"Campaign status is {campaign.status.value if hasattr(campaign.status, 'value') else campaign.status}, not APPROVED."
        )
        return PolicyCheckResult("approval", passed, reason)

    # -- aggregate helper -------------------------------------------------

    def evaluate_opportunity(
        self, *, probability: float, customer_id: uuid.UUID, policy: MerchantPolicy | None
    ) -> list[PolicyCheckResult]:
        """Every check relevant to including one payment in a new campaign."""
        return [
            self.check_recovery_probability(probability, policy),
            self.check_customer_contact_limit(customer_id, policy),
            self.check_allowed_action(policy),
        ]
