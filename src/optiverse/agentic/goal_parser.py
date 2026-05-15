"""Natural-language goal parsing helpers."""

from __future__ import annotations

import json
import textwrap
from typing import Any

from .catalog import Catalog, catalog_summary
from .layout_compiler import goal_from_planner_data
from .llm_client import LLMProviderError, LLMResponse, call_provider
from .schema import GoalSpec

PARSE_GOAL_PROMPT_VERSION = "goal-spec-v1"

PROMPT_TEMPLATES = {
    PARSE_GOAL_PROMPT_VERSION: """\
You are converting a natural-language optical experiment request into an Optiverse GoalSpec.

Return JSON only. Do not include prose or markdown fences.

The response must be either a GoalSpec object directly or an object with a top-level "goal" field.
Use only catalog_id values from the available catalog. Use origin placements only when obvious.
Otherwise, prefer planner-friendly anchors with interface_midpoint points. Preserve textbook optical
parameters such as HWP fast_axis_deg, source wavelength, polarization, target polarization, and
expected power fractions.

Natural-language request:
{request_json}

Available component catalog summary:
{catalog_json}
""",
}


def make_parse_goal_prompt(
    request: str,
    catalog: Catalog,
    *,
    prompt_version: str = PARSE_GOAL_PROMPT_VERSION,
) -> str:
    """Build a versioned prompt for natural-language GoalSpec parsing."""
    try:
        template = PROMPT_TEMPLATES[prompt_version]
    except KeyError as exc:
        raise ValueError(f"Unknown parse-goal prompt version: {prompt_version}") from exc
    return textwrap.dedent(template).format(
        request_json=json.dumps(request),
        catalog_json=json.dumps(catalog_summary(catalog), indent=2, sort_keys=True),
    )


def _goal_payload_from_response(data: dict[str, Any]) -> dict[str, Any]:
    goal = data.get("goal")
    if isinstance(goal, dict):
        return goal
    if "goal_id" in data and "source" in data:
        return data
    raise ValueError("provider response must contain a GoalSpec object or top-level goal")


def parse_goal_response(catalog: Catalog, data: dict[str, Any]) -> GoalSpec:
    """Parse provider JSON into a normalized GoalSpec."""
    return goal_from_planner_data(catalog, _goal_payload_from_response(data))


def parse_goal_with_provider(
    request: str,
    catalog: Catalog,
    *,
    provider: str,
    model: str | None = None,
    max_tokens: int = 4000,
    prompt_version: str = PARSE_GOAL_PROMPT_VERSION,
) -> tuple[GoalSpec, LLMResponse]:
    """Parse natural language into a GoalSpec through a named provider."""
    prompt = make_parse_goal_prompt(request, catalog, prompt_version=prompt_version)
    response = call_provider(provider, prompt, model=model, max_tokens=max_tokens)
    if response.parsed_json is None:
        raise LLMProviderError("Provider did not return parseable JSON.")
    return parse_goal_response(catalog, response.parsed_json), response
