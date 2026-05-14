#!/usr/bin/env python3
"""Headless proof-of-concept for agentic Optiverse layout generation.

This is intentionally small: it stands in for the "model planner" with one
hardcoded topology, then uses Optiverse's real raytracer as the verifier.

Demo goal:
    Horizontally polarized 780 nm source -> HWP -> PBS.
    Use the HWP to make a 50/50 H/V split, then hit two virtual detectors.

Outputs:
    - agentic_hwp_pbs.scene.json: assembly file loadable by the GUI
    - agentic_hwp_pbs.report.json: trace/score report
    - agentic_hwp_pbs.catalog.json: compact catalog summary used by the planner
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from optiverse.core.interface_definition import InterfaceDefinition
from optiverse.core.models import SourceParams
from optiverse.integration import create_polymorphic_element
from optiverse.integration.adapter import convert_legacy_interface_to_optical
from optiverse.platform.paths import get_builtin_library_root
from optiverse.raytracing.engine import trace_rays_polymorphic
from optiverse.raytracing.ray import RayPath


@dataclass(frozen=True)
class Placement:
    """A component selected from the catalog and placed on the table."""

    label: str
    catalog_id: str
    x_mm: float
    y_mm: float
    angle_deg: float = 0.0
    interface_overrides: dict[int, dict[str, Any]] | None = None


@dataclass(frozen=True)
class Target:
    """Virtual detector used for scoring; not yet a first-class Optiverse item."""

    name: str
    x_mm: float
    y_mm: float
    radius_mm: float
    polarization: str
    expected_power_fraction: float


def _load_builtin_catalog() -> dict[str, dict[str, Any]]:
    """Load built-in component JSON files into a planner-friendly catalog."""
    root = get_builtin_library_root()
    catalog: dict[str, dict[str, Any]] = {}

    for folder in sorted(root.iterdir()):
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


def _catalog_summary(catalog: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a compact summary that a model planner could consume."""
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


def _planner_output() -> tuple[str, SourceParams, list[Placement], list[Target]]:
    """Stand-in for a future LLM planner: return a formal topology and placements."""
    goal = (
        "Take a 780 nm horizontally polarized source, rotate it with an HWP so a PBS "
        "splits it 50/50, send H to D1 and V to D2."
    )
    source = SourceParams(
        x_mm=0.0,
        y_mm=0.0,
        angle_deg=0.0,
        size_mm=0.0,
        n_rays=1,
        ray_length_mm=500.0,
        spread_deg=0.0,
        color_hex="#DC143C",
        wavelength_nm=780.0,
        polarization_type="horizontal",
    )
    placements = [
        Placement(
            label="HWP1",
            catalog_id="waveplate_hwp",
            x_mm=60.0,
            y_mm=0.0,
            interface_overrides={0: {"fast_axis_deg": 22.5}},
        ),
        Placement(label="PBS1", catalog_id="pbs_2in", x_mm=145.0, y_mm=0.0),
    ]
    targets = [
        Target(
            name="D1_transmitted_H",
            x_mm=300.0,
            y_mm=0.0,
            radius_mm=2.0,
            polarization="horizontal",
            expected_power_fraction=0.5,
        ),
        Target(
            name="D2_reflected_V",
            x_mm=145.0,
            y_mm=-250.0,
            radius_mm=2.0,
            polarization="vertical",
            expected_power_fraction=0.5,
        ),
    ]
    return goal, source, placements, targets


def _rotate_translate(x: float, y: float, placement: Placement) -> tuple[float, float]:
    """Apply Optiverse's user angle convention to local component coordinates."""
    theta = -math.radians(placement.angle_deg)
    c = math.cos(theta)
    s = math.sin(theta)
    return (
        placement.x_mm + c * x - s * y,
        placement.y_mm + s * x + c * y,
    )


def _placed_interface(iface_data: dict[str, Any], placement: Placement) -> InterfaceDefinition:
    """Convert a component-local interface to scene coordinates."""
    iface = InterfaceDefinition.from_dict(copy.deepcopy(iface_data))
    x1, y1 = _rotate_translate(float(iface.x1_mm), float(iface.y1_mm), placement)
    x2, y2 = _rotate_translate(float(iface.x2_mm), float(iface.y2_mm), placement)
    iface.x1_mm = x1
    iface.y1_mm = y1
    iface.x2_mm = x2
    iface.y2_mm = y2
    return iface


def _compile_elements(
    catalog: dict[str, dict[str, Any]], placements: list[Placement]
) -> list[Any]:
    """Compile selected catalog components into polymorphic raytracing elements."""
    elements = []
    for placement in placements:
        component = catalog[placement.catalog_id]
        interfaces = copy.deepcopy(component.get("interfaces", []) or [])

        for index, overrides in (placement.interface_overrides or {}).items():
            interfaces[index].update(overrides)

        for iface_data in interfaces:
            placed_iface = _placed_interface(iface_data, placement)
            optical_iface = convert_legacy_interface_to_optical(placed_iface)
            elements.append(create_polymorphic_element(optical_iface))

    return elements


def _source_to_scene_item(source: SourceParams) -> dict[str, Any]:
    data = vars(source).copy()
    data["_type"] = "source"
    data["item_uuid"] = str(uuid.uuid4())
    return data


def _placement_to_scene_item(
    catalog: dict[str, dict[str, Any]], placement: Placement
) -> dict[str, Any]:
    component = copy.deepcopy(catalog[placement.catalog_id])
    interfaces = component.get("interfaces", []) or []
    for index, overrides in (placement.interface_overrides or {}).items():
        interfaces[index].update(overrides)

    component.update(
        {
            "_type": "component",
            "item_uuid": str(uuid.uuid4()),
            "x_mm": placement.x_mm,
            "y_mm": placement.y_mm,
            "angle_deg": placement.angle_deg,
            "interfaces": interfaces,
            "notes": f"Generated by agentic_layout_demo as {placement.label}",
        }
    )
    component.pop("_catalog_id", None)
    return component


def _build_scene_data(
    catalog: dict[str, dict[str, Any]], source: SourceParams, placements: list[Placement]
) -> dict[str, Any]:
    return {
        "version": "2.0",
        "items": [_source_to_scene_item(source)]
        + [_placement_to_scene_item(catalog, p) for p in placements],
        "rulers": [],
        "texts": [],
        "rectangles": [],
        "path_measures": [],
        "layer_state": {},
    }


def _point_segment_distance(
    point: np.ndarray, a: np.ndarray, b: np.ndarray
) -> tuple[float, np.ndarray]:
    ab = b - a
    denom = float(np.dot(ab, ab))
    if denom <= 1e-12:
        return float(np.linalg.norm(point - a)), a
    t = max(0.0, min(1.0, float(np.dot(point - a, ab) / denom)))
    closest = a + t * ab
    return float(np.linalg.norm(point - closest)), closest


def _polarization_overlap(path: RayPath, target_pol: str) -> float:
    pol = path.polarization.normalize().jones_vector
    if target_pol == "horizontal":
        basis = np.array([1.0, 0.0], dtype=complex)
    elif target_pol == "vertical":
        basis = np.array([0.0, 1.0], dtype=complex)
    else:
        raise ValueError(f"Unsupported target polarization: {target_pol}")
    return float(abs(np.vdot(basis, pol)) ** 2)


def _score_target(path: RayPath, target: Target) -> dict[str, Any]:
    target_point = np.array([target.x_mm, target.y_mm], dtype=float)
    best_distance = float("inf")
    best_point = None
    best_segment_index = 0

    for i, (a, b) in enumerate(zip(path.points, path.points[1:], strict=False)):
        distance, closest = _point_segment_distance(target_point, np.asarray(a), np.asarray(b))
        if distance < best_distance:
            best_distance = distance
            best_point = closest
            best_segment_index = i

    intensity_index = min(best_segment_index + 1, max(0, len(path.intensities) - 1))
    intensity = float(path.intensities[intensity_index]) if path.intensities else 0.0
    overlap = _polarization_overlap(path, target.polarization)

    return {
        "hit": best_distance <= target.radius_mm,
        "closest_distance_mm": best_distance,
        "closest_point_mm": best_point.tolist() if best_point is not None else None,
        "power_fraction": intensity,
        "expected_power_fraction": target.expected_power_fraction,
        "power_error": abs(intensity - target.expected_power_fraction),
        "polarization": target.polarization,
        "polarization_overlap": overlap,
    }


def _score_paths(paths: list[RayPath], targets: list[Target]) -> dict[str, Any]:
    target_scores = {}
    for target in targets:
        scores = [_score_target(path, target) for path in paths]
        best = min(scores, key=lambda item: item["closest_distance_mm"])
        target_scores[target.name] = best

    return {
        "target_scores": target_scores,
        "passed": all(score["hit"] for score in target_scores.values())
        and all(score["polarization_overlap"] > 0.99 for score in target_scores.values())
        and all(score["power_error"] < 1e-6 for score in target_scores.values()),
        "ray_paths": [
            {
                "points_mm": [np.asarray(point).tolist() for point in path.points],
                "intensities": [float(value) for value in path.intensities],
                "final_polarization": {
                    "Ex": [
                        float(path.polarization.jones_vector[0].real),
                        float(path.polarization.jones_vector[0].imag),
                    ],
                    "Ey": [
                        float(path.polarization.jones_vector[1].real),
                        float(path.polarization.jones_vector[1].imag),
                    ],
                },
            }
            for path in paths
        ],
    }


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("examples/output"),
        help="Directory for generated scene/report files.",
    )
    args = parser.parse_args()

    catalog = _load_builtin_catalog()
    goal, source, placements, targets = _planner_output()
    elements = _compile_elements(catalog, placements)
    paths = trace_rays_polymorphic(elements, [source], parallel=False)
    score = _score_paths(paths, targets)

    scene_data = _build_scene_data(catalog, source, placements)
    report = {
        "goal": goal,
        "topology": "source -> HWP1 -> PBS1 -> {transmitted: D1, reflected: D2}",
        "placements": [placement.__dict__ for placement in placements],
        "targets": [target.__dict__ for target in targets],
        "score": score,
    }

    out_dir = args.output_dir
    scene_path = out_dir / "agentic_hwp_pbs.scene.json"
    report_path = out_dir / "agentic_hwp_pbs.report.json"
    catalog_path = out_dir / "agentic_hwp_pbs.catalog.json"

    _write_json(scene_path, scene_data)
    _write_json(report_path, report)
    _write_json(catalog_path, _catalog_summary(catalog))

    print(f"goal: {goal}")
    print(f"paths: {len(paths)}")
    for target_name, target_score in score["target_scores"].items():
        print(
            f"{target_name}: hit={target_score['hit']} "
            f"distance={target_score['closest_distance_mm']:.6g} mm "
            f"power={target_score['power_fraction']:.6g} "
            f"pol_overlap={target_score['polarization_overlap']:.6g}"
        )
    print(f"passed: {score['passed']}")
    print(f"scene: {scene_path}")
    print(f"report: {report_path}")
    print(f"catalog: {catalog_path}")
    return 0 if score["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
