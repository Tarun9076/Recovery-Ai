"""Schema validation tests: valid shapes pass, invalid ones are rejected --
including unsupported recommended_action values (spec section 13)."""

import pytest
from pydantic import ValidationError

from app.agents.schemas import (
    Finding,
    InvestigateRequest,
    InvestigateResponse,
    RecommendedAction,
    Severity,
    StructuredDecision,
)


def _valid_finding_kwargs() -> dict:
    return dict(
        finding="UPI failures spiked",
        severity=Severity.HIGH,
        evidence=["recent share 12%", "baseline share 5%"],
        affected_payment_count=42,
        revenue_at_risk=100000.0,
        estimated_recoverable_revenue=65000.0,
    )


def _valid_decision_kwargs() -> dict:
    return dict(
        problem="UPI failures spiked",
        root_cause="Bank-side outage concentrated on one bank",
        evidence=["..."],
        revenue_at_risk=100000.0,
        recoverable_revenue=65000.0,
        recommended_action=RecommendedAction.PAYMENT_LINK,
        expected_recovery=60000.0,
        confidence=0.8,
        reason="High confidence, above policy threshold",
        requires_approval=True,
    )


def test_finding_accepts_valid_data():
    finding = Finding(**_valid_finding_kwargs())
    assert finding.severity == Severity.HIGH
    assert finding.affected_payment_count == 42


def test_finding_rejects_negative_counts():
    kwargs = _valid_finding_kwargs()
    kwargs["affected_payment_count"] = -1
    with pytest.raises(ValidationError):
        Finding(**kwargs)


def test_finding_rejects_negative_revenue():
    kwargs = _valid_finding_kwargs()
    kwargs["revenue_at_risk"] = -100.0
    with pytest.raises(ValidationError):
        Finding(**kwargs)


def test_finding_rejects_invalid_severity():
    kwargs = _valid_finding_kwargs()
    kwargs["severity"] = "catastrophic"
    with pytest.raises(ValidationError):
        Finding(**kwargs)


def test_structured_decision_accepts_valid_data():
    decision = StructuredDecision(**_valid_decision_kwargs())
    assert decision.recommended_action == RecommendedAction.PAYMENT_LINK


def test_structured_decision_rejects_unsupported_action():
    """Only the 6 actions from spec sections 7+9 are valid -- anything else
    (e.g. a made-up "AUTO_REFUND") must fail schema validation."""
    kwargs = _valid_decision_kwargs()
    kwargs["recommended_action"] = "AUTO_REFUND"
    with pytest.raises(ValidationError):
        StructuredDecision(**kwargs)


@pytest.mark.parametrize("action", list(RecommendedAction))
def test_structured_decision_accepts_every_supported_action(action):
    kwargs = _valid_decision_kwargs()
    kwargs["recommended_action"] = action
    StructuredDecision(**kwargs)  # must not raise


def test_structured_decision_rejects_confidence_out_of_range():
    kwargs = _valid_decision_kwargs()
    kwargs["confidence"] = 1.5
    with pytest.raises(ValidationError):
        StructuredDecision(**kwargs)

    kwargs["confidence"] = -0.1
    with pytest.raises(ValidationError):
        StructuredDecision(**kwargs)


def test_investigate_request_rejects_empty_question():
    with pytest.raises(ValidationError):
        InvestigateRequest(question="")


def test_investigate_response_defaults_to_empty_lists():
    response = InvestigateResponse(summary="No anomalies found.", revenue_at_risk=0.0, recoverable_revenue=0.0)
    assert response.findings == []
    assert response.recommendations == []
