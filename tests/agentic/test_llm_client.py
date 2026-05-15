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


def test_mock_provider_returns_goal_json():
    response = call_provider("mock", "parse a 50/50 HWP PBS split")

    assert response.provider == "mock"
    assert response.parsed_json is not None
    assert response.parsed_json["goal"]["placements"][0]["catalog_id"] == "waveplate_hwp"


def test_recorded_provider_reads_saved_response(tmp_path, monkeypatch):
    response_path = tmp_path / "response.json"
    response_path.write_text(json.dumps({"goal": {"goal_id": "g"}}), encoding="utf-8")
    monkeypatch.setenv("OPTIVERSE_RECORDED_LLM_RESPONSE", str(response_path))

    response = call_provider("recorded", "prompt")

    assert response.provider == "recorded"
    assert response.parsed_json == {"goal": {"goal_id": "g"}}


def test_anthropic_without_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(LLMProviderError, match="ANTHROPIC_API_KEY"):
        call_provider("anthropic", "prompt", model="claude-test")
