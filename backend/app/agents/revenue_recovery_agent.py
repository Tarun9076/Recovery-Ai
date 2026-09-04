"""The investigation agent: Observe -> Investigate -> Diagnose -> Predict ->
Recommend. Execution (actually sending a payment link, retrying a charge,
etc.) is out of scope until Phase 4/5 -- this module never writes to
`payments`, `orders`, or `merchant_policies`, and never marks anything
recovered.

## Why the LLM never calls tools itself

A classic "agent" gives the LLM a tool-calling loop: it decides which
queries to run and in what order. That's a bad fit here, for exactly the
reason the spec calls out -- "Do not allow the LLM to invent statistics."
An LLM with live tool access can still fabricate a plausible-looking
number in its *reasoning* even when the tool results are real (miscount,
misremember, round wrong), and there'd be no structural guarantee against
it.

Instead, this agent runs a **fixed, deterministic Python pipeline** over
`tools.py` (DataCollector -> FailureAnalyzer -> RootCauseAnalyzer ->
RecoveryPredictor -> OpportunityRanker -> InterventionPlanner) that
computes every number in the final response. The LLM is invoked exactly
once, at the very end, and only to write prose (`schemas.LLMNarrative`)
explaining data it's handed -- it cannot alter a single figure. Even a
total LLM hallucination can only corrupt text fields; `revenue_at_risk`,
`recoverable_revenue`, `expected_recovery`, and `confidence` always trace
back to a database query or the Phase 2 model.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlmodel import Session

from app.agents import tools
from app.agents.llm_client import LLMClient, MockLLMClient, get_llm_client
from app.agents.schemas import (
    Finding,
    InvestigateResponse,
    RecommendedAction,
    Severity,
    StructuredDecision,
)
from app.models.merchant_policy import MerchantPolicy

# Single source of truth for the "low confidence -> manual review" rule
# (spec section 9). Nothing else in this module hardcodes a confidence cut.
LOW_CONFIDENCE_THRESHOLD = 0.3

RECENT_WINDOW_DAYS = 28
BASELINE_WINDOW_DAYS = 28
MAX_FINDINGS = 5

DATA_SOURCES = ["payments", "payment_failures", "customers", "recovery_predictions", "merchant_policies"]


class DataCollector:
    """Step 1-2 of the investigation flow: retrieve payment statistics and
    compare the recent window against baseline."""

    def __init__(self, session: Session):
        self.session = session

    def collect(self, as_of: datetime | None = None) -> dict:
        overall_stats = tools.get_failure_statistics(self.session)
        spike_analysis = tools.analyze_failure_spike(
            self.session, recent_days=RECENT_WINDOW_DAYS, baseline_days=BASELINE_WINDOW_DAYS, as_of=as_of,
        )
        return {"overall_stats": overall_stats, "spike_analysis": spike_analysis}


class FailureAnalyzer:
    """Step 3: identify and severity-rank abnormal failure patterns from the
    raw anomaly list (category spikes, bank concentration, time spikes)."""

    def analyze(self, spike_analysis: dict) -> list[dict]:
        anomalies = spike_analysis.get("anomalies", [])
        scored = [(self._severity(a), self._magnitude(a), a) for a in anomalies]
        scored.sort(key=lambda t: t[1], reverse=True)
        return [{**a, "severity": sev.value} for sev, _mag, a in scored[:MAX_FINDINGS]]

    @staticmethod
    def _magnitude(anomaly: dict) -> float:
        if anomaly["type"] == "category_spike":
            return anomaly["recent_share"] - anomaly["baseline_share"]
        if anomaly["type"] == "bank_concentration":
            return anomaly["recent_failed_share"]
        if anomaly["type"] == "time_spike":
            return anomaly["z_score"]
        return 0.0

    @classmethod
    def _severity(cls, anomaly: dict) -> Severity:
        magnitude = cls._magnitude(anomaly)
        if anomaly["type"] == "time_spike":
            return Severity.HIGH if magnitude >= 3 else Severity.MEDIUM
        return Severity.HIGH if magnitude >= 0.3 else (Severity.MEDIUM if magnitude >= 0.15 else Severity.LOW)


class RecoveryPredictor:
    """Step 9: identify recoverable revenue for a set of payments, via the
    Phase 2 ML engine (never re-derived here)."""

    def __init__(self, session: Session):
        self.session = session

    def recoverable_revenue_for(self, payment_ids: list[uuid.UUID]) -> float:
        if not payment_ids:
            return 0.0
        opportunities = tools.rank_recovery_opportunities(self.session, payment_ids=payment_ids, limit=len(payment_ids))
        return sum(o["expected_recovery"] for o in opportunities)


class RootCauseAnalyzer:
    """Step 4-8: turns ranked anomalies into `Finding` objects. Every field
    is computed from `tools.get_failed_payments` output -- `evidence`
    strings are formatted directly from those numbers, never generated."""

    def __init__(self, session: Session):
        self.session = session
        self.recovery_predictor = RecoveryPredictor(session)

    def diagnose(self, spike_analysis: dict, ranked_anomalies: list[dict]) -> tuple[list[Finding], list[list[uuid.UUID]]]:
        recent_window = spike_analysis["recent_window"]
        since = datetime.fromisoformat(recent_window["since"])
        until = datetime.fromisoformat(recent_window["until"])

        findings: list[Finding] = []
        payment_id_groups: list[list[uuid.UUID]] = []
        for anomaly in ranked_anomalies:
            payments = self._affected_payments(anomaly, since, until)
            payment_ids = [uuid.UUID(p["payment_id"]) for p in payments]
            revenue_at_risk = sum(p["amount"] for p in payments)
            recoverable = self.recovery_predictor.recoverable_revenue_for(payment_ids)

            findings.append(Finding(
                finding=self._describe(anomaly),
                severity=Severity(anomaly["severity"]),
                evidence=self._evidence(anomaly),
                affected_payment_count=len(payment_ids),
                revenue_at_risk=revenue_at_risk,
                estimated_recoverable_revenue=recoverable,
            ))
            payment_id_groups.append(payment_ids)
        return findings, payment_id_groups

    def _affected_payments(self, anomaly: dict, since: datetime, until: datetime) -> list[dict]:
        # limit=10000 comfortably covers this dataset's full failed-payment
        # population (a production system would use a direct aggregate
        # query instead of capping a row fetch).
        if anomaly["type"] == "category_spike":
            return tools.get_failed_payments(self.session, since=since, until=until, category=anomaly["category"], limit=10000)
        if anomaly["type"] == "bank_concentration":
            return tools.get_failed_payments(self.session, since=since, until=until, bank=anomaly["bank"], limit=10000)
        if anomaly["type"] == "time_spike":
            # naive, matching how created_at is stored (see analyze_failure_spike's docstring)
            day_start = datetime.strptime(anomaly["date"], "%Y-%m-%d")
            return tools.get_failed_payments(self.session, since=day_start, until=day_start + timedelta(days=1), limit=10000)
        return []

    @staticmethod
    def _describe(anomaly: dict) -> str:
        if anomaly["type"] == "category_spike":
            label = anomaly["category"].replace("_", " ").title()
            return f"{label} failures rose to {anomaly['recent_share']:.0%} of failures (from a {anomaly['baseline_share']:.0%} baseline)"
        if anomaly["type"] == "bank_concentration":
            return f"Failures are disproportionately concentrated on {anomaly['bank']} ({anomaly['recent_failed_share']:.0%} of recent failures)"
        if anomaly["type"] == "time_spike":
            return f"Failures spiked on {anomaly['date']} ({anomaly['failed_count']} failures, {anomaly['z_score']:.1f} std. deviations above the window average)"
        return "Unrecognized anomaly"

    @staticmethod
    def _evidence(anomaly: dict) -> list[str]:
        if anomaly["type"] == "category_spike":
            return [
                f"Recent share of failures: {anomaly['recent_share']:.1%}",
                f"Baseline share of failures: {anomaly['baseline_share']:.1%}",
                f"Recent failed count: {anomaly['recent_count']}",
            ]
        if anomaly["type"] == "bank_concentration":
            return [
                f"Recent failed count on this bank: {anomaly['recent_failed_count']}",
                f"Share of all recent failures: {anomaly['recent_failed_share']:.1%}",
            ]
        if anomaly["type"] == "time_spike":
            return [
                f"Failed count on this day: {anomaly['failed_count']}",
                f"Z-score vs. recent-window daily average: {anomaly['z_score']}",
            ]
        return []


class OpportunityRanker:
    """Ranks recovery opportunities by expected_recovery (Phase 2), scoped
    to a specific set of payments when given one."""

    def __init__(self, session: Session):
        self.session = session

    def top_opportunities(self, payment_ids: list[uuid.UUID] | None, limit: int = 20) -> list[dict]:
        if payment_ids is not None and not payment_ids:
            return []
        return tools.rank_recovery_opportunities(self.session, payment_ids=payment_ids, limit=limit)


def _cap_by_customer(opportunities: list[dict], max_contacts: int) -> list[dict]:
    """Merchant policy: don't recommend contacting the same customer more
    than `max_customer_contacts` times. `opportunities` is already sorted
    by expected_recovery descending, so this keeps each customer's best
    opportunity/opportunities and drops the rest."""
    seen: dict[str, int] = {}
    capped = []
    for opp in opportunities:
        customer_id = opp["customer_id"]
        if seen.get(customer_id, 0) >= max_contacts:
            continue
        seen[customer_id] = seen.get(customer_id, 0) + 1
        capped.append(opp)
    return capped


class InterventionPlanner:
    """Step 10 + the policy gate (spec sections 7-9): proposes one action
    per finding, constrained by the merchant's own policy and the model's
    confidence -- never by LLM discretion."""

    def plan(self, finding: Finding, opportunities: list[dict], policy: MerchantPolicy | None) -> StructuredDecision:
        base = {
            "problem": finding.finding,
            "root_cause": finding.finding,
            "evidence": finding.evidence,
            "revenue_at_risk": finding.revenue_at_risk,
            "recoverable_revenue": finding.estimated_recoverable_revenue,
        }

        if not opportunities:
            return StructuredDecision(
                **base, recommended_action=RecommendedAction.NO_ACTION, expected_recovery=0.0,
                confidence=0.0, reason="No payments in this finding have a positive predicted recovery probability.",
                requires_approval=False,
            )

        if policy is not None and not policy.allowed_actions:
            avg_confidence = sum(o["confidence"] for o in opportunities) / len(opportunities)
            return StructuredDecision(
                **base, recommended_action=RecommendedAction.NO_ACTION, expected_recovery=0.0,
                confidence=avg_confidence,
                reason="Merchant policy has no allowed outreach channels configured -- no intervention can be delivered.",
                requires_approval=False,
            )

        threshold = policy.minimum_recovery_probability if policy else 0.65
        max_contacts = policy.max_customer_contacts if policy else 1
        approval_required = policy.approval_required if policy else True

        capped = _cap_by_customer(opportunities, max_contacts)
        avg_confidence = sum(o["confidence"] for o in opportunities) / len(opportunities)
        avg_probability = sum(o["recovery_probability"] for o in opportunities) / len(opportunities)

        if avg_confidence < LOW_CONFIDENCE_THRESHOLD:
            return StructuredDecision(
                **base, recommended_action=RecommendedAction.MANUAL_REVIEW, expected_recovery=0.0,
                confidence=avg_confidence,
                reason=f"Average model confidence ({avg_confidence:.0%}) is below the {LOW_CONFIDENCE_THRESHOLD:.0%} threshold for an automated recommendation.",
                requires_approval=False,
            )

        if avg_probability < threshold:
            return StructuredDecision(
                **base, recommended_action=RecommendedAction.MANUAL_REVIEW, expected_recovery=0.0,
                confidence=avg_confidence,
                reason=f"Average recovery probability ({avg_probability:.0%}) is below the merchant's policy threshold ({threshold:.0%}).",
                requires_approval=False,
            )

        expected_recovery = sum(o["expected_recovery"] for o in capped)
        contacted_note = (
            f" (capped to {len(capped)} of {len(opportunities)} payments by the merchant's "
            f"max_customer_contacts={max_contacts} policy)" if len(capped) < len(opportunities) else ""
        )
        return StructuredDecision(
            **base,
            recommended_action=RecommendedAction.PAYMENT_LINK,
            expected_recovery=expected_recovery,
            confidence=avg_confidence,
            reason=(
                f"{len(capped)} payment(s) qualify above the merchant's {threshold:.0%} recovery-probability "
                f"threshold with {avg_confidence:.0%} average model confidence{contacted_note}."
            ),
            requires_approval=approval_required,
        )


def _safe_list_get(items: list, index: int, default):
    return items[index] if index < len(items) else default


class RevenueRecoveryAgent:
    def __init__(self, session: Session, llm_client: LLMClient | None = None):
        self.session = session
        self.llm_client = llm_client or get_llm_client()
        self.data_collector = DataCollector(session)
        self.failure_analyzer = FailureAnalyzer()
        self.root_cause_analyzer = RootCauseAnalyzer(session)
        self.opportunity_ranker = OpportunityRanker(session)
        self.intervention_planner = InterventionPlanner()
        # Populated by investigate() -- read by the API layer to build the audit record.
        self.last_tools_used: list[str] = []
        self.last_data_sources: list[str] = []

    def investigate(self, question: str) -> InvestigateResponse:
        tools_used = ["get_failure_statistics", "analyze_failure_spike"]

        collected = self.data_collector.collect()
        ranked_anomalies = self.failure_analyzer.analyze(collected["spike_analysis"])
        findings, payment_id_groups = self.root_cause_analyzer.diagnose(collected["spike_analysis"], ranked_anomalies)
        if findings:
            tools_used += ["get_failed_payments", "rank_recovery_opportunities"]

        policy = tools.get_merchant_policy(self.session)
        recovery_metrics = tools.get_recovery_metrics(self.session)
        tools_used.append("get_recovery_metrics")

        draft_recommendations: list[StructuredDecision] = []
        for finding, payment_ids in zip(findings, payment_id_groups):
            opportunities = self.opportunity_ranker.top_opportunities(payment_ids, limit=max(len(payment_ids), 1))
            draft_recommendations.append(self.intervention_planner.plan(finding, opportunities, policy))

        try:
            narrative = self.llm_client.generate_narrative(
                question,
                collected["overall_stats"],
                collected["spike_analysis"],
                [f.model_dump(mode="json") for f in findings],
                recovery_metrics,
                [d.model_dump(mode="json") for d in draft_recommendations],
            )
        except Exception:
            # Last-resort safety net -- GeminiLLMClient already falls back
            # internally, so this should only trigger for a custom
            # llm_client passed in that has no fallback of its own.
            narrative = MockLLMClient().generate_narrative(
                question, collected["overall_stats"], collected["spike_analysis"],
                [f.model_dump(mode="json") for f in findings], recovery_metrics,
                [d.model_dump(mode="json") for d in draft_recommendations],
            )

        final_recommendations = [
            decision.model_copy(update={
                "root_cause": _safe_list_get(narrative.root_cause_narratives, i, decision.root_cause),
                "reason": _safe_list_get(narrative.recommendation_reasons, i, decision.reason),
            })
            for i, decision in enumerate(draft_recommendations)
        ]

        self.last_tools_used = tools_used
        self.last_data_sources = DATA_SOURCES

        return InvestigateResponse(
            summary=narrative.summary,
            findings=findings,
            revenue_at_risk=sum(f.revenue_at_risk for f in findings),
            recoverable_revenue=sum(f.estimated_recoverable_revenue for f in findings),
            recommendations=final_recommendations,
        )
