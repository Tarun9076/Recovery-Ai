"""Recovery **action** selection -- deliberately separate from recovery
**prediction**.

Bug this module fixes (Phase 9): every failed payment that passed the
generic "is this worth pursuing" policy checks (probability threshold,
contact limit, allowed channels) was recommended `PAYMENT_LINK`, regardless
of *why* the payment failed. A TIMEOUT, a CARD_LIMIT, an INVALID_DETAILS,
and an UNKNOWN failure all got the same recommendation as long as the ML
model scored them high enough. That conflates two different questions:

    ML model            -> "Is this payment worth attempting to recover?"
                            (a probability -- see recovery_predictor.py)
    RecoveryActionSelector -> "What is the appropriate recovery action for
                            THIS SPECIFIC failed payment?"
                            (this module)

The ML model is untouched by this fix -- `recovery_probability` still means
exactly what it always meant, and nothing here retrains or reinterprets it.
This module only decides what to *do* with that probability, given the
failure's own context (category, customer history, attempt number, whether
this failure category is currently spiking) and the merchant's policy.

## Executability

The `PaymentProvider` abstraction (see `payment_provider.py`) can only ever
do one thing: create a payment link. `EXECUTABLE_ACTIONS` names the only
`RecommendedAction` values a campaign may actually execute -- everything
else is a recommendation the merchant/audit trail can see (and the
opportunity table can show), but `campaign_service.create_campaign` will
never include it in a real, executable campaign, and
`_execute_campaign`'s own final guard (see campaign_service.py) refuses to
call the provider for it even if it somehow did.

## Fail-closed default

An unrecognized or missing failure category is never silently treated as
"safe to send a payment link" -- see `_category_policy`'s fallback. This is
the specific regression the bug report named: "unknown failure reason ->
MANUAL_REVIEW", never "-> GENERATE_PAYMENT_LINK".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from app.agents.tools import get_latest_payment_timestamp
from app.models.customer import Customer
from app.models.enums import FailureCategory, RecommendedAction
from app.models.merchant_policy import MerchantPolicy
from app.models.payment import Payment
from app.models.payment_failure import PaymentFailure
from app.services.policy_engine import PolicyCheckResult, PolicyEngine

# Beyond this many attempts on the same order, stop proactively re-sending
# payment links and ask for a human look instead -- "retry limit not
# exceeded" is one of the explicit context signals the action policy must
# respect, not just probability.
MAX_PROACTIVE_RETRY_ATTEMPTS = 3

# Only PAYMENT_LINK maps to a real `PaymentProvider.create_recovery_link()`
# call. Every other action is a recommendation the current provider
# abstraction cannot itself deliver -- see this module's docstring.
EXECUTABLE_ACTIONS: frozenset[RecommendedAction] = frozenset({RecommendedAction.PAYMENT_LINK})

# Spike-detection windows, mirroring app.agents.tools.analyze_failure_spike's
# own recent-vs-baseline comparison (same 1.5x share threshold, same
# minimum-count floor) so "is this failure category currently spiking"
# means the same thing here as it does in the investigation agent's own
# anomaly detection -- not a second, differently-tuned definition of spike.
SPIKE_RECENT_DAYS = 7
SPIKE_BASELINE_DAYS = 21
SPIKE_MIN_RECENT_COUNT = 10
SPIKE_SHARE_MULTIPLIER = 1.5

# Categories genuinely amenable to "just try to collect again" -- transient
# or gateway-side failures where the same payment could plausibly succeed on
# a fresh attempt. Everything else gets its own explicit policy below.
_PROACTIVE_RETRY_CATEGORIES = frozenset({
    FailureCategory.TIMEOUT,
    FailureCategory.NETWORK_ERROR,
    FailureCategory.UPI_FAILURE,
    FailureCategory.BANK_DECLINED,
    FailureCategory.AUTHENTICATION_FAILURE,
})

# Narrower still: categories genuinely likely to be a one-off blip with no
# gateway/bank decision behind them at all, where "the customer probably
# just retries on their own" is a credible bet -- not every category in
# _PROACTIVE_RETRY_CATEGORIES qualifies (a UPI/bank decline is still a
# deliberate rejection, not a dropped connection).
_PASSIVE_RETRY_CATEGORIES = frozenset({FailureCategory.TIMEOUT, FailureCategory.NETWORK_ERROR})

# Deliberately a high, near-certain bar -- RETRY (no proactive outreach) is
# meant to be the rare exception for an obviously-going-to-resolve-itself
# payment, not the default outcome for every payment that merely clears the
# merchant's ordinary recovery-probability threshold.
PASSIVE_RETRY_PROBABILITY_FLOOR = 0.95

CategorySpikeMap = dict[FailureCategory, bool]


@dataclass
class ActionDecision:
    """The action-selection layer's structured output. Mirrors the
    project's existing `PolicyCheckResult` conventions (a `reason` string
    always explains the outcome) rather than inventing a parallel shape."""

    action: RecommendedAction
    eligible: bool
    reason: str
    confidence: float
    expected_recovery: float
    policy_checks: list[PolicyCheckResult] = field(default_factory=list)

    @property
    def executable(self) -> bool:
        """Whether a campaign built from this decision can actually be
        executed by the current `PaymentProvider` -- see EXECUTABLE_ACTIONS.
        `eligible` alone is not enough: a decision can be "eligible" (the
        policy layer approves proactive contact) but still map to an action
        (e.g. ALTERNATIVE_PAYMENT_METHOD) nothing in this codebase can
        actually deliver yet."""
        return self.eligible and self.action in EXECUTABLE_ACTIONS

    def as_dict(self) -> dict:
        return {
            "action": self.action.value,
            "eligible": self.eligible,
            "executable": self.executable,
            "reason": self.reason,
            "confidence": self.confidence,
            "expected_recovery": self.expected_recovery,
            "policy_checks": [c.as_dict() for c in self.policy_checks],
        }


def compute_category_spike_map(session: Session, *, as_of: datetime | None = None) -> CategorySpikeMap:
    """Which failure categories are currently spiking, computed ONCE (two
    GROUP BY aggregate queries, not one query per payment/category) so
    `RecoveryActionSelector` can be called in a loop over many payments
    without turning into the N+1 pattern this project has already had to
    fix twice elsewhere (see recovery_predictor.py and webhook_service.py's
    Phase 8 performance notes). Callers processing more than one payment in
    the same request/batch MUST compute this once and pass it in, rather
    than letting `RecoveryActionSelector.select` compute it per call.

    `as_of` defaults to the latest payment in the database, not wall-clock
    time -- same reasoning as `analyze_failure_spike` (this is a fixed
    historical dataset; anchoring to real time would make "recent" drift
    away from any actual data)."""
    if as_of is None:
        as_of = get_latest_payment_timestamp(session) or datetime.now().replace(tzinfo=None)
    recent_start = as_of - timedelta(days=SPIKE_RECENT_DAYS)
    baseline_start = recent_start - timedelta(days=SPIKE_BASELINE_DAYS)

    recent_rows = session.exec(
        select(PaymentFailure.failure_category, func.count())
        .join(Payment, Payment.id == PaymentFailure.payment_id)
        .where(Payment.created_at >= recent_start, Payment.created_at <= as_of)
        .group_by(PaymentFailure.failure_category)
    ).all()
    baseline_rows = session.exec(
        select(PaymentFailure.failure_category, func.count())
        .join(Payment, Payment.id == PaymentFailure.payment_id)
        .where(Payment.created_at >= baseline_start, Payment.created_at < recent_start)
        .group_by(PaymentFailure.failure_category)
    ).all()

    recent_counts = dict(recent_rows)
    baseline_counts = dict(baseline_rows)
    recent_total = max(sum(recent_counts.values()), 1)
    baseline_total = max(sum(baseline_counts.values()), 1)

    spike_map: CategorySpikeMap = {}
    for category in set(recent_counts) | set(baseline_counts):
        recent_count = recent_counts.get(category, 0)
        recent_share = recent_count / recent_total
        baseline_share = baseline_counts.get(category, 0) / baseline_total
        spike_map[category] = (
            recent_count >= SPIKE_MIN_RECENT_COUNT
            and baseline_share > 0
            and recent_share > baseline_share * SPIKE_SHARE_MULTIPLIER
        )
    return spike_map


def _category_policy(
    category: FailureCategory | None, *,
    probability: float, threshold: float, spiking: bool,
    attempt_number: int, customer_has_prior_success: bool,
) -> tuple[RecommendedAction, bool, str]:
    """Returns (action, proactive_contact_eligible, reason) for a payment
    that has ALREADY cleared the generic policy gate (probability threshold,
    contact limit, allowed channels -- see PolicyEngine). This is where
    failure-category context, plus payment/customer context (attempt number,
    prior successful payments), turns "the customer is worth contacting"
    into "here is specifically how".

    Fail-closed default: any category not explicitly handled below --
    including FailureCategory.UNKNOWN and a missing failure record entirely
    -- resolves to MANUAL_REVIEW, never PAYMENT_LINK. This is the fix for
    the reported bug: a new/unrecognized failure type must never accidentally
    trigger a financial action."""
    if category is None or category == FailureCategory.UNKNOWN:
        return (
            RecommendedAction.MANUAL_REVIEW, False,
            "Failure reason is missing or unrecognized -- no safe automated action; needs manual review.",
        )

    if category == FailureCategory.INVALID_DETAILS:
        # Sending a payment link doesn't help if what the customer entered
        # (email/contact/etc.) was wrong to begin with -- they need to fix
        # that first, regardless of how likely the model thinks recovery is.
        return (
            RecommendedAction.REQUEST_CUSTOMER_CORRECTION, True,
            "Payment details were invalid -- ask the customer to correct them before any retry can succeed.",
        )

    if category in (FailureCategory.CARD_DECLINED, FailureCategory.CARD_LIMIT):
        # The same card is likely to fail again the same way; recommend a
        # different method instead of resending a link for the same card.
        return (
            RecommendedAction.ALTERNATIVE_PAYMENT_METHOD, True,
            f"{category.value.replace('_', ' ').title()} -- the same card is likely to fail again; "
            f"recommend an alternative payment method rather than retrying it.",
        )

    if category == FailureCategory.INSUFFICIENT_FUNDS:
        # A payment link sent while funds are known to be short just fails
        # again; wait unless the model is highly confident (e.g. salary-day
        # timing) that funds are now available.
        if probability >= threshold + 0.15:
            return (
                RecommendedAction.PAYMENT_LINK, True,
                f"Insufficient funds previously, but recovery probability ({probability:.0%}) is well above "
                f"threshold -- likely resolved; safe to send a payment link.",
            )
        return (
            RecommendedAction.DEFER, False,
            f"Insufficient funds -- recovery probability ({probability:.0%}) doesn't clear the higher bar "
            f"needed to assume funds are now available; defer rather than contact now.",
        )

    if category in _PROACTIVE_RETRY_CATEGORIES:
        label = category.value.replace("_", " ").title()

        if spiking:
            # A systemic issue (bank/gateway/network-side), not this one
            # customer -- don't mass-contact every affected customer while
            # it's still ongoing; wait for it to clear.
            return (
                RecommendedAction.DEFER, False,
                f"{label} failures are currently spiking (systemic pattern, not specific to this payment) "
                f"-- defer rather than contacting every affected customer individually while the underlying "
                f"issue is ongoing.",
            )

        if attempt_number > MAX_PROACTIVE_RETRY_ATTEMPTS:
            # Already retried enough times on this same order that another
            # automatic link is unlikely to help -- a human should look at
            # why it keeps failing rather than the system trying again blindly.
            return (
                RecommendedAction.MANUAL_REVIEW, False,
                f"{label}, but this is attempt #{attempt_number} on this order (limit "
                f"{MAX_PROACTIVE_RETRY_ATTEMPTS}) -- repeated automatic retries haven't worked; needs manual review.",
            )

        if (
            category in _PASSIVE_RETRY_CATEGORIES
            and attempt_number == 1
            and customer_has_prior_success
            and probability >= PASSIVE_RETRY_PROBABILITY_FLOOR
        ):
            # Genuinely transient (timeout/network-level, not a gateway
            # decline), first attempt, a customer with a track record of
            # actually paying, and near-certain to recover -- likely to
            # self-resolve on their own next try. Recommend monitoring
            # rather than spending a proactive outreach/contact-limit slot
            # on a customer who probably didn't need it. Deliberately a high
            # bar (not just "above the policy threshold"): this is meant to
            # be the exception, not the default outcome for every qualifying
            # payment -- see this module's docstring.
            return (
                RecommendedAction.RETRY, False,
                f"{label} on a first attempt from a customer with a successful payment history and recovery "
                f"probability ({probability:.0%}) near-certain -- likely to self-resolve; recommend "
                f"monitoring for an organic retry rather than proactive outreach.",
            )

        return (
            RecommendedAction.PAYMENT_LINK, True,
            f"{label} is transient and isolated (no recent spike in this category, retry limit not "
            f"exceeded) -- safe to proactively send a payment link.",
        )

    if category == FailureCategory.TECHNICAL_ERROR:
        # Less predictable than a plain timeout/network blip -- worth a
        # human glance rather than an automatic send, even though it still
        # only reaches here after clearing the probability threshold.
        return (
            RecommendedAction.MANUAL_REVIEW, False,
            "Technical error -- cause is ambiguous enough to warrant a manual look before an automated send.",
        )

    # Should be unreachable (every FailureCategory member is handled above),
    # but if a new category is ever added to the enum without updating this
    # function, fail closed exactly like the None/UNKNOWN case rather than
    # falling through to anything financial.
    return (
        RecommendedAction.MANUAL_REVIEW, False,
        f"No action policy defined for failure category {category.value!r} -- needs manual review.",
    )


class RecoveryActionSelector:
    """The dedicated action-selection/policy layer (spec: "Action Selection
    Engine"). Reuses `PolicyEngine` for every generic merchant-guardrail
    check (probability threshold, customer contact limit, allowed outreach
    channels) rather than re-implementing them -- this class only adds the
    failure-category-specific layer on top, per this module's docstring."""

    def __init__(self, session: Session):
        self.session = session
        self.policy_engine = PolicyEngine(session)

    def select(
        self,
        *,
        payment: Payment,
        failure: PaymentFailure | None,
        recovery_probability: float,
        expected_recovery: float,
        confidence: float,
        policy: MerchantPolicy | None,
        customer: Customer | None = None,
        spike_map: CategorySpikeMap | None = None,
        check_contact_limit: bool = True,
    ) -> ActionDecision:
        """`spike_map` should be computed once per request/batch via
        `compute_category_spike_map` and passed in when selecting for more
        than one payment -- see that function's docstring. `check_contact_limit`
        can be disabled for read-only preview listings (e.g. the opportunity
        browse table) where re-validating against a customer's contact
        history isn't the source of truth anyway -- campaign creation always
        re-runs the full check regardless (see campaign_service.py).
        `customer` is optional -- if not supplied, it's fetched by primary
        key (a single indexed lookup, effectively free, not a scan) since
        `payment.customer_id` is always available."""
        if customer is None:
            customer = self.session.get(Customer, payment.customer_id)

        threshold = policy.minimum_recovery_probability if policy else 0.65

        checks = [self.policy_engine.check_recovery_probability(recovery_probability, policy)]
        if check_contact_limit:
            checks.append(self.policy_engine.check_customer_contact_limit(payment.customer_id, policy))
        checks.append(self.policy_engine.check_allowed_action(policy))

        low_confidence_threshold = 0.3  # matches app.agents.revenue_recovery_agent.LOW_CONFIDENCE_THRESHOLD
        if confidence < low_confidence_threshold:
            return ActionDecision(
                action=RecommendedAction.MANUAL_REVIEW, eligible=False,
                reason=f"Model confidence ({confidence:.0%}) is below the manual-review threshold.",
                confidence=confidence, expected_recovery=0.0, policy_checks=checks,
            )

        if not all(c.passed for c in checks):
            failed_reasons = "; ".join(c.reason for c in checks if not c.passed)
            return ActionDecision(
                action=RecommendedAction.NO_ACTION, eligible=False,
                reason=f"Does not qualify: {failed_reasons}",
                confidence=confidence, expected_recovery=0.0, policy_checks=checks,
            )

        category = failure.failure_category if failure else None
        spiking = bool(spike_map.get(category, False)) if (spike_map is not None and category is not None) else False
        customer_has_prior_success = bool(customer and customer.successful_payment_count > 0)
        action, eligible, category_reason = _category_policy(
            category, probability=recovery_probability, threshold=threshold, spiking=spiking,
            attempt_number=payment.attempt_number, customer_has_prior_success=customer_has_prior_success,
        )

        return ActionDecision(
            action=action, eligible=eligible,
            reason=category_reason,
            confidence=confidence,
            expected_recovery=expected_recovery if eligible else 0.0,
            policy_checks=checks,
        )
