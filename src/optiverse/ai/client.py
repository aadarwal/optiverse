"""LLM client for generating beam path specifications."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

_logger = logging.getLogger(__name__)


class LLMClient:
    """
    Thin wrapper around OpenAI's chat completions API.

    Requires the ``openai`` package and an ``OPENAI_API_KEY`` env var.
    Uses JSON mode to guarantee parseable output.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """
        Send a prompt to the LLM and return the parsed JSON response.

        Raises:
            ImportError: if ``openai`` is not installed.
            RuntimeError: if the API call fails or the response is not valid JSON.
        """
        try:
            import openai
        except ImportError:
            raise ImportError(
                "The 'openai' package is required for AI generation. "
                "Install it with:  pip install 'optiverse[ai]'"
            ) from None

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY environment variable is not set. "
                "Export it before running:  export OPENAI_API_KEY='sk-...'"
            )

        client = openai.OpenAI(api_key=api_key)

        _logger.info("Calling %s with %d-char system prompt", self.model, len(system_prompt))

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        except Exception as exc:
            raise RuntimeError(f"OpenAI API call failed: {exc}") from exc

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned empty response")

        _logger.debug("Raw LLM response: %s", content[:500])

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM returned invalid JSON: {exc}\n{content[:500]}") from exc

        return data
