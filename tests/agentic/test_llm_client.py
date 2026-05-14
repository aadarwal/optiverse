import json

import pytest

from optiverse.agentic.llm_client import LLMProviderError, call_provider, extract_json_object


def test_extract_json_object_accepts_plain_json():
    assert extract_json_object('{"placements": []}') == {"placements": []}


def test_extract_json_object_accepts_markdown_fence():
    text = "```json\n" + json.dumps({"topology": "source -> lens"}) + "\n```"

    assert extract_json_object(text) == {"topology": "source -> lens"}


def test_unknown_provider_raises_clear_error():
    with pytest.raises(LLMProviderError, match="Unsupported provider"):
        call_provider("not-a-provider", "{}")
