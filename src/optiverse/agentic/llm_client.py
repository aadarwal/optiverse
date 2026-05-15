"""Optional LLM provider adapters for agentic layout experiments."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import demo_goal_spec


class LLMProviderError(RuntimeError):
    """Raised when an optional LLM provider cannot run."""


@dataclass(frozen=True)
class LLMResponse:
    """Raw and parsed LLM response."""

    provider: str
    model: str
    prompt: str
    raw_text: str
    parsed_json: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt": self.prompt,
            "raw_text": self.raw_text,
            "parsed_json": self.parsed_json,
        }


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from plain text or a markdown fenced response."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(stripped[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON must be an object")
    return parsed


def call_anthropic(prompt: str, *, model: str | None = None, max_tokens: int = 4000) -> LLMResponse:
    """Call Anthropic when the optional SDK, API key, and model are available."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMProviderError("Set ANTHROPIC_API_KEY or use the manual saved-output path.")

    model_name = model or os.environ.get("ANTHROPIC_MODEL")
    if not model_name:
        raise LLMProviderError("Pass --model or set ANTHROPIC_MODEL for the Anthropic provider.")

    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LLMProviderError(
            "Install the optional Anthropic SDK with `pip install anthropic`."
        ) from exc

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model_name,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_parts = []
    for block in message.content:
        text = getattr(block, "text", None)
        if text is not None:
            raw_parts.append(text)
    raw_text = "\n".join(raw_parts).strip()

    parsed_json = None
    try:
        parsed_json = extract_json_object(raw_text)
    except Exception:
        parsed_json = None

    return LLMResponse(
        provider="anthropic",
        model=model_name,
        prompt=prompt,
        raw_text=raw_text,
        parsed_json=parsed_json,
    )


def call_mock(prompt: str, *, model: str | None = None, max_tokens: int = 4000) -> LLMResponse:
    """Return deterministic JSON for local tests and no-network workflows."""
    del max_tokens
    model_name = model or "mock-goal-v1"
    goal = demo_goal_spec()
    goal_payload = goal.to_dict()
    goal_payload["description"] = (
        "Mock parsed goal: 780 nm horizontal beam split 50/50 by HWP/PBS."
    )

    parsed_json: dict[str, Any]
    if "explicit Optiverse component placements" in prompt:
        parsed_json = {
            "placements": [placement.to_dict() for placement in goal.placements],
        }
    elif "topology/intent" in prompt:
        parsed_json = {
            "topology": goal.topology,
            "components": [placement.label for placement in goal.placements],
        }
    else:
        parsed_json = {
            "prompt_version": "goal-spec-v1",
            "goal": goal_payload,
        }
    raw_text = json.dumps(parsed_json, indent=2)
    return LLMResponse(
        provider="mock",
        model=model_name,
        prompt=prompt,
        raw_text=raw_text,
        parsed_json=parsed_json,
    )


def call_recorded(
    prompt: str, *, model: str | None = None, max_tokens: int = 4000
) -> LLMResponse:
    """Read a saved provider response from OPTIVERSE_RECORDED_LLM_RESPONSE."""
    del max_tokens
    path_value = os.environ.get("OPTIVERSE_RECORDED_LLM_RESPONSE")
    if not path_value:
        raise LLMProviderError(
            "Set OPTIVERSE_RECORDED_LLM_RESPONSE to a saved JSON/text response path."
        )
    raw_text = Path(path_value).read_text(encoding="utf-8")
    parsed_json = None
    try:
        parsed_json = extract_json_object(raw_text)
    except Exception:
        parsed_json = None
    return LLMResponse(
        provider="recorded",
        model=model or "recorded-response",
        prompt=prompt,
        raw_text=raw_text,
        parsed_json=parsed_json,
    )


def call_provider(
    provider: str, prompt: str, *, model: str | None = None, max_tokens: int = 4000
) -> LLMResponse:
    """Call an optional LLM provider."""
    normalized = provider.lower()
    if normalized == "anthropic":
        return call_anthropic(prompt, model=model, max_tokens=max_tokens)
    if normalized == "mock":
        return call_mock(prompt, model=model, max_tokens=max_tokens)
    if normalized == "recorded":
        return call_recorded(prompt, model=model, max_tokens=max_tokens)
    raise LLMProviderError(f"Unsupported provider: {provider}")
