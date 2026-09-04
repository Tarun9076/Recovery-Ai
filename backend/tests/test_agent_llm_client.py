"""LLM client tests: malformed JSON recovers gracefully (spec section 13),
the mock client is deterministic and network-free, and get_llm_client()
picks the right implementation based on config."""

from app.agents.llm_client import GeminiLLMClient, MockLLMClient, _parse_narrative, get_llm_client
from app.agents.schemas import LLMNarrative


def _sample_inputs():
    findings = [{
        "finding": "UPI failures spiked", "severity": "high", "evidence": ["a", "b"],
        "affected_payment_count": 20, "revenue_at_risk": 50000.0, "estimated_recoverable_revenue": 30000.0,
    }]
    draft = [{
        "problem": "UPI failures spiked", "root_cause": "UPI failures spiked", "evidence": ["a"],
        "revenue_at_risk": 50000.0, "recoverable_revenue": 30000.0, "recommended_action": "PAYMENT_LINK",
        "expected_recovery": 28000.0, "confidence": 0.8, "reason": "qualifies", "requires_approval": True,
    }]
    return {
        "question": "Why did revenue drop?",
        "failure_stats": {"failure_rate": 0.07},
        "spike_analysis": {"recent_window": {"failure_rate": 0.07}, "baseline_window": {"failure_rate": 0.05}, "failure_rate_change_pct": 0.4},
        "findings": findings,
        "recovery_metrics": {"total_predictions": 20},
        "draft_recommendations": draft,
    }


def test_mock_client_produces_valid_narrative_from_findings():
    client = MockLLMClient()
    inputs = _sample_inputs()
    narrative = client.generate_narrative(
        inputs["question"], inputs["failure_stats"], inputs["spike_analysis"],
        inputs["findings"], inputs["recovery_metrics"], inputs["draft_recommendations"],
    )
    assert isinstance(narrative, LLMNarrative)
    assert "UPI failures spiked" in narrative.summary
    assert len(narrative.root_cause_narratives) == 1
    assert len(narrative.recommendation_reasons) == 1


def test_mock_client_handles_no_findings():
    client = MockLLMClient()
    narrative = client.generate_narrative(
        "Why did revenue drop?", {"failure_rate": 0.05},
        {"recent_window": {"failure_rate": 0.05}, "baseline_window": {"failure_rate": 0.05}, "failure_rate_change_pct": 0.0},
        [], {"total_predictions": 0}, [],
    )
    assert isinstance(narrative, LLMNarrative)
    assert narrative.root_cause_narratives == []
    assert narrative.recommendation_reasons == []


def test_mock_client_is_deterministic():
    client = MockLLMClient()
    inputs = _sample_inputs()
    first = client.generate_narrative(
        inputs["question"], inputs["failure_stats"], inputs["spike_analysis"],
        inputs["findings"], inputs["recovery_metrics"], inputs["draft_recommendations"],
    )
    second = client.generate_narrative(
        inputs["question"], inputs["failure_stats"], inputs["spike_analysis"],
        inputs["findings"], inputs["recovery_metrics"], inputs["draft_recommendations"],
    )
    assert first == second


def test_parse_narrative_strips_markdown_fences():
    raw = '```json\n{"summary": "ok", "root_cause_narratives": [], "recommendation_reasons": []}\n```'
    narrative = _parse_narrative(raw)
    assert narrative.summary == "ok"


def test_parse_narrative_raises_on_malformed_json():
    import json

    import pytest
    with pytest.raises(json.JSONDecodeError):
        _parse_narrative("not json at all {{{")


class _AlwaysMalformedFakeGeminiClient(GeminiLLMClient):
    """Simulates a live LLM that only ever returns garbage -- exercises the
    retry-then-fallback path without a network call."""

    def __init__(self):  # deliberately skip the real __init__ (no API client needed)
        pass

    def _call(self, user_prompt: str) -> str:
        return "this is not valid json"


def test_llm_client_falls_back_to_mock_after_repeated_malformed_output():
    client = _AlwaysMalformedFakeGeminiClient()
    inputs = _sample_inputs()
    narrative = client.generate_narrative(
        inputs["question"], inputs["failure_stats"], inputs["spike_analysis"],
        inputs["findings"], inputs["recovery_metrics"], inputs["draft_recommendations"],
    )
    # Must not raise -- graceful fallback to a valid, schema-conforming narrative.
    assert isinstance(narrative, LLMNarrative)
    assert narrative.summary


class _FlakyThenValidFakeGeminiClient(GeminiLLMClient):
    """First call malformed, second call (after the retry prompt) valid --
    exercises the one-retry-then-succeed path."""

    def __init__(self):
        self.calls = 0

    def _call(self, user_prompt: str) -> str:
        self.calls += 1
        if self.calls == 1:
            return "garbage"
        return '{"summary": "recovered on retry", "root_cause_narratives": ["x"], "recommendation_reasons": ["y"]}'


def test_llm_client_recovers_on_retry():
    client = _FlakyThenValidFakeGeminiClient()
    inputs = _sample_inputs()
    narrative = client.generate_narrative(
        inputs["question"], inputs["failure_stats"], inputs["spike_analysis"],
        inputs["findings"], inputs["recovery_metrics"], inputs["draft_recommendations"],
    )
    assert narrative.summary == "recovered on retry"
    assert client.calls == 2


def test_get_llm_client_returns_mock_when_no_api_key(monkeypatch):
    from app.core import config

    monkeypatch.setenv("LLM_API_KEY", "")
    config.get_settings.cache_clear()
    try:
        client = get_llm_client()
        assert isinstance(client, MockLLMClient)
    finally:
        config.get_settings.cache_clear()
