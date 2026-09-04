"""Revenue-recovery metrics (spec section 7). Always computed from source
rows -- `payments`, `recovery_opportunities`, `recovery_actions` -- never
from a cached/stored total, so a campaign's numbers can never drift out of
sync with its actions. `revenue_recovered` sums only
`RecoveryAction.recovered_amount` (set exclusively by a verified webhook,
see webhook_service.py) -- it is never derived from `expected_recovery`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.enums import PaymentStatus, RecoveryActionStatus
from app.models.payment import Payment
from app.models.payment_failure import PaymentFailure
from app.models.recovery_action import RecoveryAction
from app.models.recovery_campaign import RecoveryCampaign
from app.models.recovery_opportunity import RecoveryOpportunity


@dataclass
class RecoveryMetrics:
    revenue_at_risk: float
    recoverable_revenue: float
    revenue_recovered: float

    @property
    def recovery_rate(self) -> float:
        """Recovery Rate = Actual Revenue Recovered / Recoverable Revenue (spec section 7)."""
        return (self.revenue_recovered / self.recoverable_revenue) if self.recoverable_revenue > 0 else 0.0

    def as_dict(self) -> dict:
        return {
            "revenue_at_risk": self.revenue_at_risk,
            "recoverable_revenue": self.recoverable_revenue,
            "revenue_recovered": self.revenue_recovered,
            "recovery_rate": round(self.recovery_rate, 4),
        }


def compute_campaign_metrics(session: Session, campaign: RecoveryCampaign) -> RecoveryMetrics:
    """Scoped to one campaign: at-risk/recoverable are the totals fixed at
    creation time (`total_amount`/`expected_recovery`, already computed by
    `campaign_service.create_campaign` from real predictions -- see that
    module); recovered is summed fresh from this campaign's own actions."""
    recovered = session.exec(
        select(func.coalesce(func.sum(RecoveryAction.recovered_amount), 0.0)).where(
            RecoveryAction.campaign_id == campaign.id,
            RecoveryAction.status == RecoveryActionStatus.RECOVERED,
        )
    ).one()
    return RecoveryMetrics(
        revenue_at_risk=campaign.total_amount,
        recoverable_revenue=campaign.expected_recovery,
        revenue_recovered=float(recovered),
    )


def compute_portfolio_metrics(session: Session) -> RecoveryMetrics:
    """Global, across every failed payment / opportunity / action."""
    from app.models.recovery_prediction import RecoveryPrediction

    revenue_at_risk = session.exec(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(Payment.status == PaymentStatus.failed)
    ).one()
    pred_recoverable = session.exec(
        select(func.coalesce(func.sum(RecoveryPrediction.expected_recovery), 0.0))
    ).one()
    opp_recoverable = session.exec(
        select(func.coalesce(func.sum(RecoveryOpportunity.expected_recovery), 0.0))
    ).one()
    recoverable_revenue = max(float(pred_recoverable), float(opp_recoverable))

    revenue_recovered = session.exec(
        select(func.coalesce(func.sum(RecoveryAction.recovered_amount), 0.0)).where(
            RecoveryAction.status == RecoveryActionStatus.RECOVERED
        )
    ).one()
    return RecoveryMetrics(
        revenue_at_risk=float(revenue_at_risk),
        recoverable_revenue=float(recoverable_revenue),
        revenue_recovered=float(revenue_recovered),
    )


@dataclass
class BaselineComparison:
    """Phase 8 (spec: "Baseline vs RecoverAI comparison using actual
    simulation results"). Deliberately scoped to only the failed payments
    RecoverAI actually targeted with a recovery action (i.e. every payment
    that has at least one `RecoveryAction`) -- comparing that population's
    outcomes is a fair like-for-like measurement. Comparing against the
    *entire* failed-payment portfolio instead would be misleading: most
    failed payments in a 50k-100k dataset are never touched by any
    campaign during a demo run, so their organic recovery would swamp the
    handful RecoverAI actually worked on and make RecoverAI look like it
    hurt overall recovery, when it simply hasn't been run against most of
    the portfolio yet.

    "Baseline" is what that same targeted population would have recovered
    with *zero* AI/campaign intervention -- the synthetic dataset's own
    `eventually_recovered` ground truth (see `scripts/generate_data.py`),
    which models organic customer retry behaviour. This never exposes that
    ground truth per-payment (it stays out of every prediction/opportunity
    API, unchanged since Phase 2) -- only a single aggregate SUM, over
    payments RecoverAI already chose to act on, is computed here, purely
    for this retrospective report. "RecoverAI" is the real recovered
    revenue for that same population: money actually confirmed by a
    verified webhook (see `webhook_service.py`), not a prediction.
    """

    targeted_transaction_value: float
    targeted_payment_count: int
    baseline_recovered_revenue: float
    recoverai_recovered_revenue: float

    @property
    def incremental_recovered_revenue(self) -> float:
        return self.recoverai_recovered_revenue - self.baseline_recovered_revenue

    @property
    def baseline_recovery_rate(self) -> float:
        return (self.baseline_recovered_revenue / self.targeted_transaction_value) if self.targeted_transaction_value > 0 else 0.0

    @property
    def recoverai_recovery_rate(self) -> float:
        return (self.recoverai_recovered_revenue / self.targeted_transaction_value) if self.targeted_transaction_value > 0 else 0.0

    def as_dict(self) -> dict:
        return {
            "targeted_transaction_value": self.targeted_transaction_value,
            "targeted_payment_count": self.targeted_payment_count,
            "baseline_recovered_revenue": self.baseline_recovered_revenue,
            "recoverai_recovered_revenue": self.recoverai_recovered_revenue,
            "incremental_recovered_revenue": round(self.incremental_recovered_revenue, 2),
            "baseline_recovery_rate": round(self.baseline_recovery_rate, 4),
            "recoverai_recovery_rate": round(self.recoverai_recovery_rate, 4),
        }


def compute_baseline_comparison(session: Session) -> BaselineComparison:
    """Restricted throughout to `payments.id IN (SELECT DISTINCT payment_id
    FROM recovery_actions)` -- payments RecoverAI actually created at least
    one recovery action for, regardless of that action's outcome."""
    targeted_payment_ids = select(RecoveryAction.payment_id).distinct().subquery()

    targeted_count, targeted_value = session.exec(
        select(func.count(), func.coalesce(func.sum(Payment.amount), 0.0))
        .select_from(Payment)
        .join(targeted_payment_ids, targeted_payment_ids.c.payment_id == Payment.id)
    ).one()

    baseline_recovered = session.exec(
        select(func.coalesce(func.sum(Payment.amount), 0.0))
        .select_from(Payment)
        .join(targeted_payment_ids, targeted_payment_ids.c.payment_id == Payment.id)
        .join(PaymentFailure, PaymentFailure.payment_id == Payment.id)
        .where(PaymentFailure.eventually_recovered.is_(True))
    ).one()

    recoverai_recovered = session.exec(
        select(func.coalesce(func.sum(RecoveryAction.recovered_amount), 0.0)).where(
            RecoveryAction.status == RecoveryActionStatus.RECOVERED
        )
    ).one()

    return BaselineComparison(
        targeted_transaction_value=float(targeted_value),
        targeted_payment_count=int(targeted_count),
        baseline_recovered_revenue=float(baseline_recovered),
        recoverai_recovered_revenue=float(recoverai_recovered),
    )
