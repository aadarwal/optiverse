"""Component catalog loading for the headless agentic harness."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from optiverse.platform.paths import get_builtin_library_root

Catalog = dict[str, dict[str, Any]]


def load_builtin_catalog(root: Path | None = None) -> Catalog:
    """Load built-in component JSON files keyed by catalog folder ID."""
    library_root = root if root is not None else get_builtin_library_root()
    catalog: Catalog = {}

    for folder in sorted(library_root.iterdir()):
        component_path = folder / "component.json"
        if not component_path.exists():
            continue

        data = json.loads(component_path.read_text(encoding="utf-8"))
        data["_catalog_id"] = folder.name

        image_path = data.get("image_path")
        if isinstance(image_path, str) and image_path and not Path(image_path).is_absolute():
            data["image_path"] = f"objects/library/{folder.name}/{image_path}"

        catalog[folder.name] = data

    return catalog


def clone_component(catalog: Catalog, catalog_id: str) -> dict[str, Any]:
    """Return a mutable deep copy of a catalog component."""
    if catalog_id not in catalog:
        raise KeyError(f"Unknown catalog_id: {catalog_id}")
    return copy.deepcopy(catalog[catalog_id])


def catalog_summary(catalog: Catalog) -> list[dict[str, Any]]:
    """Return a compact summary suitable for prompts and reports."""
    summary = []
    for catalog_id, data in sorted(catalog.items()):
        interfaces = data.get("interfaces", []) or []
        summary.append(
            {
                "catalog_id": catalog_id,
                "name": data.get("name", catalog_id),
                "category": data.get("category", ""),
                "object_height_mm": data.get("object_height_mm", 0.0),
                "interfaces": [
                    {
                        "element_type": iface.get("element_type"),
                        "subtype": iface.get("polarizer_subtype"),
                        "efl_mm": iface.get("efl_mm"),
                        "phase_shift_deg": iface.get("phase_shift_deg"),
                        "is_polarizing": iface.get("is_polarizing"),
                    }
                    for iface in interfaces
                ],
            }
        )
    return summary
