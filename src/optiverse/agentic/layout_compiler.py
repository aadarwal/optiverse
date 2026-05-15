"""Planner-facing placement normalization for agentic layouts."""

from __future__ import annotations

import copy
from typing import Any

from .catalog import Catalog
from .compiler import interfaces_for_placement, placed_interface
from .schema import GoalSpec, Placement


def _raw_anchor(data: dict[str, Any]) -> dict[str, Any] | None:
    anchor = data.get("anchor")
    if isinstance(anchor, dict):
        return dict(anchor)
    if "anchor_x_mm" in data or "anchor_y_mm" in data:
        return {
            "kind": data.get("anchor_kind", "interface_midpoint"),
            "x_mm": data.get("anchor_x_mm"),
            "y_mm": data.get("anchor_y_mm"),
            "interface_index": data.get("interface_index", 0),
        }
    return None


def _base_placement(data: dict[str, Any], *, x_mm: float, y_mm: float) -> Placement:
    placement_data = dict(data)
    placement_data.pop("anchor", None)
    placement_data.pop("anchor_x_mm", None)
    placement_data.pop("anchor_y_mm", None)
    placement_data.pop("anchor_kind", None)
    placement_data["x_mm"] = x_mm
    placement_data["y_mm"] = y_mm
    return Placement.from_dict(placement_data)


def _interface_point_offset(
    catalog: Catalog, placement: Placement, interface_index: int, kind: str
) -> tuple[float, float]:
    interfaces = interfaces_for_placement(catalog, placement)
    if interface_index < 0 or interface_index >= len(interfaces):
        raise ValueError(
            f"interface_index {interface_index} does not exist on {placement.catalog_id}"
        )
    iface = placed_interface(interfaces[interface_index], placement)
    if kind in {"interface_midpoint", "midpoint"}:
        return (
            0.5 * (float(iface.x1_mm) + float(iface.x2_mm)),
            0.5 * (float(iface.y1_mm) + float(iface.y2_mm)),
        )
    if kind in {"interface_start", "p1"}:
        return float(iface.x1_mm), float(iface.y1_mm)
    if kind in {"interface_end", "p2"}:
        return float(iface.x2_mm), float(iface.y2_mm)
    raise ValueError(f"unsupported anchor kind: {kind}")


def _effective_focal_length_mm(
    catalog: Catalog, placement: Placement, interface_index: int
) -> float:
    interfaces = interfaces_for_placement(catalog, placement)
    if interface_index < 0 or interface_index >= len(interfaces):
        raise ValueError(
            f"interface_index {interface_index} does not exist on {placement.catalog_id}"
        )
    focal_length = interfaces[interface_index].get("efl_mm")
    if focal_length is None:
        raise ValueError(f"{placement.label} interface {interface_index} has no efl_mm")
    return float(focal_length)


def _spacing_mm(
    catalog: Catalog,
    anchor: dict[str, Any],
    current: Placement,
    reference: Placement | None,
    interface_index: int,
) -> float:
    if "distance_mm" in anchor:
        return float(anchor["distance_mm"])
    spacing = str(anchor.get("spacing", "0")).lower()
    if spacing in {"", "0", "none"}:
        return 0.0
    if reference is None:
        raise ValueError(f"spacing '{spacing}' requires anchor.relative_to")
    reference_index = int(anchor.get("reference_interface_index", interface_index))
    reference_f = _effective_focal_length_mm(catalog, reference, reference_index)
    current_f = _effective_focal_length_mm(catalog, current, interface_index)
    if spacing in {"f1_plus_f2", "focal_length_sum", "relay_spacing"}:
        return reference_f + current_f
    if spacing in {"reference_focal_length", "f1"}:
        return reference_f
    if spacing in {"current_focal_length", "f2"}:
        return current_f
    raise ValueError(f"unsupported focal spacing: {spacing}")


def _anchor_target_point(
    catalog: Catalog,
    anchor: dict[str, Any],
    current: Placement,
    prior: dict[str, Placement],
    interface_index: int,
) -> tuple[float, float]:
    relative_to = anchor.get("relative_to")
    if relative_to is None:
        return float(anchor["x_mm"]), float(anchor["y_mm"])

    reference_label = str(relative_to)
    reference = prior.get(reference_label)
    if reference is None:
        raise ValueError(f"anchor.relative_to '{reference_label}' has not been placed")
    reference_index = int(anchor.get("reference_interface_index", interface_index))
    base_x, base_y = _interface_point_offset(
        catalog,
        reference,
        reference_index,
        str(anchor.get("reference_kind", "interface_midpoint")),
    )
    distance = _spacing_mm(catalog, anchor, current, reference, interface_index)
    direction = float(anchor.get("direction", 1.0))
    axis = str(anchor.get("axis", "x")).lower()
    dx = float(anchor.get("dx_mm", 0.0))
    dy = float(anchor.get("dy_mm", 0.0))
    if axis == "x":
        dx += direction * distance
    elif axis == "y":
        dy += direction * distance
    else:
        raise ValueError(f"unsupported relative anchor axis: {axis}")

    return (
        float(anchor["x_mm"]) if "x_mm" in anchor else base_x + dx,
        float(anchor["y_mm"]) if "y_mm" in anchor else base_y + dy,
    )


def placement_from_planner_data(
    catalog: Catalog, data: dict[str, Any], prior: dict[str, Placement] | None = None
) -> Placement:
    """Create an origin-based Placement from origin or planner anchor data."""
    anchor = _raw_anchor(data)
    if anchor is None:
        return Placement.from_dict(data)

    interface_index = int(anchor.get("interface_index", data.get("interface_index", 0)))
    kind = str(anchor.get("kind", "interface_midpoint"))
    current_at_origin = _base_placement(data, x_mm=0.0, y_mm=0.0)
    target_x, target_y = _anchor_target_point(
        catalog,
        anchor,
        current_at_origin,
        prior or {},
        interface_index,
    )
    offset_x, offset_y = _interface_point_offset(
        catalog,
        current_at_origin,
        interface_index,
        kind,
    )
    return _base_placement(data, x_mm=target_x - offset_x, y_mm=target_y - offset_y)


def placements_from_planner_data(
    catalog: Catalog, raw_placements: list[dict[str, Any]]
) -> list[Placement]:
    """Normalize a list of origin or anchored placement dictionaries."""
    placements: list[Placement] = []
    by_label: dict[str, Placement] = {}
    for raw in raw_placements:
        placement = placement_from_planner_data(catalog, raw, by_label)
        placements.append(placement)
        by_label[placement.label] = placement
    return placements


def goal_from_planner_data(catalog: Catalog, data: dict[str, Any]) -> GoalSpec:
    """Parse a GoalSpec dictionary while accepting planner-friendly placements."""
    goal_data = copy.deepcopy(data)
    raw_placements = goal_data.get("placements", [])
    if not isinstance(raw_placements, list):
        raise ValueError("goal.placements must be a list")
    goal_data["placements"] = [
        placement.to_dict()
        for placement in placements_from_planner_data(catalog, raw_placements)
    ]
    return GoalSpec.from_dict(goal_data)
