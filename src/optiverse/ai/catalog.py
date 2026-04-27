"""Scan library directories and build the component catalog for LLM context."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..core.interface_types import INTERFACE_TYPES

_logger = logging.getLogger(__name__)


def _default_library_dir() -> Path:
    """Return the built-in library directory."""
    return Path(__file__).resolve().parent.parent / "objects" / "library"


def scan_library(library_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """
    Scan a library directory and return raw component.json data keyed by library_id.

    The library_id is the directory name (e.g. "mirror_standard_1in").
    """
    if library_dir is None:
        library_dir = _default_library_dir()

    catalog: dict[str, dict[str, Any]] = {}
    if not library_dir.is_dir():
        _logger.warning("Library directory not found: %s", library_dir)
        return catalog

    for comp_dir in sorted(library_dir.iterdir()):
        comp_json = comp_dir / "component.json"
        if not comp_json.is_file():
            continue
        try:
            data = json.loads(comp_json.read_text(encoding="utf-8"))
            catalog[comp_dir.name] = data
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("Failed to read %s: %s", comp_json, exc)

    return catalog


def get_interface_types_text() -> str:
    """Return the INTERFACE_TYPES registry as formatted text for the LLM."""
    lines: list[str] = []
    for type_name, info in INTERFACE_TYPES.items():
        lines.append(f"### {info.get('name', type_name)} (`{type_name}`)")
        lines.append(f"  {info.get('description', '')}")
        props = info.get("properties", [])
        if props:
            lines.append("  Properties:")
            for p in props:
                label = info.get("property_labels", {}).get(p, p)
                unit = info.get("property_units", {}).get(p, "")
                rng = info.get("property_ranges", {}).get(p)
                default = info.get("property_defaults", {}).get(p)
                parts = [f"    - {label} (`{p}`)"]
                if unit:
                    parts.append(f"unit={unit}")
                if rng:
                    parts.append(f"range={rng}")
                if default is not None:
                    parts.append(f"default={default}")
                lines.append("  ".join(parts))
        lines.append("")
    return "\n".join(lines)


def get_catalog_text(catalog: dict[str, dict[str, Any]] | None = None) -> str:
    """Return all component.json files as formatted text for the LLM."""
    if catalog is None:
        catalog = scan_library()

    lines: list[str] = []
    for lib_id, data in catalog.items():
        lines.append(f"### `{lib_id}`")
        lines.append(f"```json\n{json.dumps(data, indent=2)}\n```")
        lines.append("")
    return "\n".join(lines)
