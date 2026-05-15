"""Packaging checks for the Optiverse agentic design plugin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "optiverse-agentic-design"


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def test_claude_plugin_manifest_points_at_skill() -> None:
    manifest = _read_json(PLUGIN_ROOT / ".claude-plugin" / "plugin.json")

    assert manifest["name"] == "optiverse-agentic-design"
    assert manifest["skills"] == "./skills/"
    assert "TODO" not in json.dumps(manifest)
    assert (PLUGIN_ROOT / "skills" / "optiverse-design" / "SKILL.md").is_file()


def test_codex_plugin_manifest_points_at_skill() -> None:
    manifest = _read_json(PLUGIN_ROOT / ".codex-plugin" / "plugin.json")

    assert manifest["name"] == "optiverse-agentic-design"
    assert manifest["skills"] == "./skills/"
    assert "TODO" not in json.dumps(manifest)


def test_skill_frontmatter_and_workflow_commands() -> None:
    skill_path = PLUGIN_ROOT / "skills" / "optiverse-design" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    _separator, frontmatter, body = text.split("---", 2)
    metadata = {
        line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip()
        for line in frontmatter.splitlines()
        if ":" in line
    }

    assert metadata["name"] == "optiverse-design"
    assert "optiverse-agent CLI" in metadata["description"]
    for command in ("catalog", "compile", "validate", "trace", "score", "render", "open"):
        assert f"optiverse-agent {command}" in body


def test_local_marketplaces_reference_plugin() -> None:
    claude_marketplace = _read_json(REPO_ROOT / ".claude-plugin" / "marketplace.json")
    assert claude_marketplace["name"] == "optiverse-local"
    claude_plugin = claude_marketplace["plugins"][0]
    assert claude_plugin["name"] == "optiverse-agentic-design"
    assert claude_plugin["source"] == "./plugins/optiverse-agentic-design"

    codex_marketplace = _read_json(REPO_ROOT / ".agents" / "plugins" / "marketplace.json")
    assert codex_marketplace["name"] == "optiverse-local"
    codex_plugin = codex_marketplace["plugins"][0]
    assert codex_plugin["name"] == "optiverse-agentic-design"
    assert codex_plugin["source"]["path"] == "./plugins/optiverse-agentic-design"
