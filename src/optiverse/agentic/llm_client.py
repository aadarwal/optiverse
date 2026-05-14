"""Optional LLM provider adapters for agentic layout experiments."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


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


def call_provider(
    provider: str, prompt: str, *, model: str | None = None, max_tokens: int = 4000
) -> LLMResponse:
    """Call an optional LLM provider."""
    if provider == "anthropic":
        return call_anthropic(prompt, model=model, max_tokens=max_tokens)
    raise LLMProviderError(f"Unsupported provider: {provider}")
