"""Build the LLM system prompt by combining CONTEXT.md with the dynamic catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .catalog import get_catalog_text, get_interface_types_text, scan_library

_CONTEXT_PATH = Path(__file__).resolve().parent / "CONTEXT.md"


def load_context() -> str:
    """Load the static CONTEXT.md file."""
    return _CONTEXT_PATH.read_text(encoding="utf-8")


def build_system_prompt(catalog: dict[str, dict[str, Any]] | None = None) -> str:
    """
    Assemble the full system prompt for the LLM.

    Sections:
      1. CONTEXT.md (rules, schema, examples)
      2. Available component catalog (raw component.json dumps)
      3. Interface types registry

    The catalog is generated dynamically so it always reflects the current
    library contents.
    """
    if catalog is None:
        catalog = scan_library()

    parts: list[str] = [
        load_context(),
        "\n---\n",
        "## 8. Available Components (Raw Library Data)\n\n",
        "Below are the raw `component.json` files for every library component.\n"
        "Use the directory name as the `library_id`.\n\n",
        get_catalog_text(catalog),
        "\n---\n",
        "## 9. Interface Types Reference\n\n",
        "Each interface's `element_type` field maps to one of the types below.\n"
        "You can override any listed property via `overrides`.\n\n",
        get_interface_types_text(),
    ]

    library_ids = sorted(catalog.keys())
    parts.append("\n---\n")
    parts.append("## 10. Quick Reference — library_id values\n\n")
    parts.append("```\n")
    for lid in library_ids:
        name = catalog[lid].get("name", lid)
        parts.append(f"  {lid:40s}  {name}\n")
    parts.append("```\n")

    return "".join(parts)
