"""Component catalog loading for the headless agentic harness."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from optiverse.platform.paths import get_builtin_library_root

Catalog = dict[str, dict[str, Any]]
OPTICAL_PARAMETER_KEYS = (
    "efl_mm",
    "clear_aperture_mm",
    "phase_shift_deg",
    "fast_axis_deg",
    "split_T",
    "split_R",
    "is_polarizing",
    "pbs_transmission_axis_deg",
    "cutoff_wavelength_nm",
    "transition_width_nm",
    "pass_type",
    "transmission_axis_deg",
    "extinction_ratio_db",
    "rotation_angle_deg",
)


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


def interface_summary(iface: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic, prompt-facing interface metadata."""
    return {
        "element_type": iface.get("element_type"),
        "subtype": iface.get("polarizer_subtype"),
        **{key: iface[key] for key in OPTICAL_PARAMETER_KEYS if key in iface},
    }


def infer_capabilities(component: dict[str, Any]) -> list[str]:
    """Infer coarse component capabilities from built-in catalog metadata."""
    capabilities: set[str] = set()
    category = str(component.get("category", "")).lower()
    catalog_id = str(component.get("_catalog_id", "")).lower()
    interfaces = component.get("interfaces", []) or []

    if category == "sources" or catalog_id.startswith("source"):
        capabilities.add("source")

    for iface in interfaces:
        element_type = str(iface.get("element_type", "")).lower()
        subtype = str(iface.get("polarizer_subtype", "")).lower()

        if element_type in {
            "lens",
            "refractive",
            "refractive_interface",
            "beam_splitter",
            "beamsplitter",
            "dichroic",
            "polarizing_interface",
            "faraday_rotator",
            "linear_polarizer",
        }:
            capabilities.add("pass_through")

        if element_type in {"mirror", "beam_splitter", "beamsplitter", "dichroic"}:
            capabilities.add("reflects")

        if element_type in {"beam_splitter", "beamsplitter", "dichroic"}:
            capabilities.add("splits")

        if (
            element_type in {"polarizing_interface", "faraday_rotator", "linear_polarizer"}
            or subtype in {"waveplate", "linear_polarizer"}
            or bool(iface.get("is_polarizing"))
        ):
            capabilities.add("polarization_control")

        if element_type == "beam_block":
            capabilities.add("absorbs")

        if element_type == "lens" or "efl_mm" in iface:
            capabilities.add("focuses")

    return sorted(capabilities)


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
                "interfaces": [interface_summary(iface) for iface in interfaces],
                "capabilities": infer_capabilities(data),
            }
        )
    return summary
