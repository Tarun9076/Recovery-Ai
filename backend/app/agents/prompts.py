"""Prompt templates for the investigation agent's single LLM call.

The LLM is invoked exactly once per investigation, after all data
collection and analysis is already done in Python. It receives the fully
computed findings/opportunities as JSON and is asked only for prose
(`schemas.LLMNarrative`) -- see `revenue_recovery_agent.py` for why numeric
fields are never taken from the LLM.
"""

from __future__ import annotations

import json

SYSTEM_PROMPT = """You are RecoverAI's investigation analyst. A merchant asked a question about \
their payment failures. You have been given pre-computed, verified statistics from their \
database and a machine-learning recovery model -- every number in the data below is already \
correct and final.

Your job is ONLY to explain what the data shows and why, in clear merchant-facing language. You \
must NOT invent, estimate, recompute, or adjust any number. Every claim you make must be \
traceable to a number or field present in the data you were given. All monetary figures in the \
data are Indian Rupees -- always format them with the ₹ symbol (e.g. ₹1,58,530), never $ or any \
other currency.

Respond with ONLY a JSON object matching this shape, no markdown fences, no extra text:
{
  "summary": "2-4 sentence plain-language answer to the merchant's question",
  "root_cause_narratives": ["one sentence per finding, explaining that finding in plain language"],
  "recommendation_reasons": ["one sentence per recommendation, explaining why that action makes sense"]
}

`root_cause_narratives` must have exactly one entry per finding provided, in the same order.
`recommendation_reasons` must have exactly one entry per recommendation provided, in the same order.
"""


def build_user_prompt(
    question: str,
    failure_stats: dict,
    spike_analysis: dict,
    findings: list[dict],
    recovery_metrics: dict,
    draft_recommendations: list[dict],
) -> str:
    payload = {
        "merchant_question": question,
        "overall_failure_statistics": failure_stats,
        "spike_vs_baseline_analysis": spike_analysis,
        "root_cause_findings": findings,
        "recovery_model_metrics": recovery_metrics,
        "draft_recommendations": draft_recommendations,
    }
    return (
        "Here is the verified data for this investigation. Use only what is here.\n\n"
        + json.dumps(payload, indent=2, default=str)
    )


RETRY_SUFFIX = (
    "\n\nYour previous response was not valid JSON matching the required shape "
    "({error}). Respond again with ONLY the corrected JSON object -- no markdown "
    "fences, no commentary, nothing before or after the JSON."
)
