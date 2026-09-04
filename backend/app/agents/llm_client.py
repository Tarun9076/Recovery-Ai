"""Pluggable LLM client for the investigation agent.

`get_llm_client()` returns a `GeminiLLMClient` if `LLM_API_KEY` is
configured, otherwise a `MockLLMClient` -- a deterministic, template-based
narrative generator with no network calls. The mock is not a stub-for-tests
convenience: it's a real fallback path, also used when the live LLM
repeatedly returns unparseable output, so `POST /api/ai/investigate` always
returns a valid response either way (spec: "If the LLM returns malformed
JSON, recover gracefully").

Swapping providers (Gemini -> OpenAI/Groq/etc.) means implementing this
same `LLMClient` interface -- nothing else in the agent changes.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

from pydantic import ValidationError

from app.agents.prompts import RETRY_SUFFIX, SYSTEM_PROMPT, build_user_prompt
from app.agents.schemas import LLMNarrative
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    @abstractmethod
    def generate_narrative(
        self,
        question: str,
        failure_stats: dict,
        spike_analysis: dict,
        findings: list[dict],
        recovery_metrics: dict,
        draft_recommendations: list[dict],
    ) -> LLMNarrative:
        raise NotImplementedError


def _parse_narrative(raw_text: str) -> LLMNarrative:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    data = json.loads(text)
    return LLMNarrative.model_validate(data)


class GeminiLLMClient(LLMClient):
    def __init__(self, api_key: str, model: str):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    def _call(self, user_prompt: str) -> str:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        return response.text or ""

    def generate_narrative(
        self, question, failure_stats, spike_analysis, findings, recovery_metrics, draft_recommendations,
    ) -> LLMNarrative:
        user_prompt = build_user_prompt(
            question, failure_stats, spike_analysis, findings, recovery_metrics, draft_recommendations
        )

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                raw = self._call(user_prompt)
                return _parse_narrative(raw)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                logger.warning("LLM returned invalid narrative JSON (attempt %d): %s", attempt + 1, exc)
                user_prompt = user_prompt + RETRY_SUFFIX.format(error=str(exc))
            except Exception as exc:  # network/API errors -- don't retry, fall back immediately
                last_error = exc
                logger.warning("LLM call failed: %s", exc)
                break

        logger.warning("Falling back to deterministic narrative after LLM failure: %s", last_error)
        return MockLLMClient().generate_narrative(
            question, failure_stats, spike_analysis, findings, recovery_metrics, draft_recommendations
        )


class MockLLMClient(LLMClient):
    """Deterministic, template-based narrative -- no randomness, no network.
    Every sentence is built directly from the structured data it's given."""

    def generate_narrative(
        self, question, failure_stats, spike_analysis, findings, recovery_metrics, draft_recommendations,
    ) -> LLMNarrative:
        recent = spike_analysis.get("recent_window", {})
        baseline = spike_analysis.get("baseline_window", {})
        rate_change = spike_analysis.get("failure_rate_change_pct")

        if findings:
            top = findings[0]
            change_phrase = (
                f", up {rate_change:+.0%} versus the prior period" if rate_change is not None else ""
            )
            summary = (
                f"Failure rate over the recent window was {recent.get('failure_rate', 0):.1%}"
                f"{change_phrase}. The leading factor is: {top['finding']} "
                f"(₹{top['revenue_at_risk']:,.0f} at risk, ₹{top['estimated_recoverable_revenue']:,.0f} "
                f"estimated recoverable)."
            )
        else:
            summary = (
                f"No statistically significant failure anomalies were found in the recent window "
                f"(failure rate {recent.get('failure_rate', 0):.1%} vs baseline "
                f"{baseline.get('failure_rate', 0):.1%})."
            )

        root_cause_narratives = [
            f"{f['finding']}: {f['affected_payment_count']} payments affected, "
            f"₹{f['revenue_at_risk']:,.0f} in revenue at risk."
            for f in findings
        ]

        recommendation_reasons = []
        for rec in draft_recommendations:
            action = rec.get("recommended_action")
            confidence = rec.get("confidence", 0.0)
            if action == "NO_ACTION":
                recommendation_reasons.append(rec.get("reason") or "Policy or data does not support an automated recommendation.")
            elif action == "MANUAL_REVIEW":
                recommendation_reasons.append(
                    f"Model confidence ({confidence:.0%}) is below the threshold for an automated "
                    f"recommendation; flagged for manual review instead."
                )
            else:
                recommendation_reasons.append(
                    f"Recovery model confidence is {confidence:.0%} with an expected recovery of "
                    f"₹{rec.get('expected_recovery', 0):,.0f}, supporting a {action} action."
                )

        return LLMNarrative(
            summary=summary,
            root_cause_narratives=root_cause_narratives,
            recommendation_reasons=recommendation_reasons,
        )


def get_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.llm_api_key:
        return GeminiLLMClient(settings.llm_api_key, settings.llm_model)
    return MockLLMClient()
