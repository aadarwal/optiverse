"""Assemble solver output into optiverse v2.0 assembly JSON."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from .solver import PlacedComponent

_logger = logging.getLogger(__name__)


def _source_item_dict(placed: PlacedComponent, catalog_entry: dict[str, Any]) -> dict[str, Any]:
    """Build an item dict for a source component."""
    d: dict[str, Any] = {}
    d["_type"] = "source"
    d["x_mm"] = placed.x_mm
    d["y_mm"] = placed.y_mm
    d["angle_deg"] = placed.angle_deg

    defaults = {
        "size_mm": 10.0,
        "n_rays": 5,
        "ray_length_mm": 500.0,
        "spread_deg": 0.0,
        "color_hex": "#FF0000",
        "wavelength_nm": 633.0,
        "polarization_type": "horizontal",
        "polarization_angle_deg": 0.0,
        "source_type": "ray",
        "beam_waist_mm": 0.5,
    }
    for k, v in defaults.items():
        d[k] = catalog_entry.get(k, v)

    for k, v in placed.overrides.items():
        d[k] = v

    if "name" not in d:
        d["name"] = catalog_entry.get("name", placed.id)

    return d


def _component_item_dict(
    placed: PlacedComponent,
    catalog_entry: dict[str, Any],
    library_dir: Path,
) -> dict[str, Any]:
    """Build an item dict for an optical component."""
    d: dict[str, Any] = {}
    d["_type"] = "component"
    d["x_mm"] = placed.x_mm
    d["y_mm"] = placed.y_mm
    d["angle_deg"] = placed.angle_deg

    d["object_height_mm"] = catalog_entry.get("object_height_mm", 30.0)

    image_path = catalog_entry.get("image_path", "")
    if image_path:
        d["image_path"] = f"@component/{placed.library_id}/{image_path}"
    else:
        d["image_path"] = ""

    d["interfaces"] = copy.deepcopy(catalog_entry.get("interfaces", []))

    for iface in d["interfaces"]:
        for k, v in placed.overrides.items():
            if k in iface:
                iface[k] = v

    if "name" not in placed.overrides:
        d["name"] = catalog_entry.get("name", placed.id)
    else:
        d["name"] = placed.overrides["name"]

    return d


def assemble(
    placed_components: list[PlacedComponent],
    catalog: dict[str, dict[str, Any]] | None = None,
    library_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Build an optiverse v2.0 assembly JSON from placed components.

    Args:
        placed_components: Solver output with positions/angles.
        catalog: {library_id: component.json data}.  Loaded from default if None.
        library_dir: Path to library root (for image path resolution).

    Returns:
        Complete v2.0 assembly dict ready for json.dump.
    """
    if catalog is None:
        from .catalog import scan_library
        catalog = scan_library()
    if library_dir is None:
        from .catalog import _default_library_dir
        library_dir = _default_library_dir()

    items: list[dict[str, Any]] = []

    for placed in placed_components:
        entry = catalog.get(placed.library_id)
        if entry is None:
            _logger.warning("No catalog entry for library_id '%s', skipping", placed.library_id)
            continue

        cat = entry.get("category", "")
        if cat == "sources" or placed.library_id.startswith("source"):
            items.append(_source_item_dict(placed, entry))
        else:
            items.append(_component_item_dict(placed, entry, library_dir))

    assembly: dict[str, Any] = {
        "version": "2.0",
        "items": items,
        "rulers": [],
        "texts": [],
        "rectangles": [],
        "path_measures": [],
        "layer_state": {},
    }
    return assembly


def assembly_to_json(assembly: dict[str, Any], indent: int = 2) -> str:
    """Serialize assembly dict to JSON string."""
    return json.dumps(assembly, indent=indent, ensure_ascii=False)
