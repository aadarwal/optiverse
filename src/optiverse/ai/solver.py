"""
Deterministic layout solver: converts a beam path specification into exact
component positions and orientations.

Coordinate conventions (optiverse scene):
  - X-right, Y-down
  - angle_deg is user convention: CW from right
    0° = right, 90° = down, 180° = left, 270° = up
  - Direction vector for angle θ: (cos(θ), sin(θ))

Orientation rules derived from optiverse raytracing geometry:
  Source:              angle = outgoing beam angle
  Pass-through:       angle = beam direction  (lens, waveplate, polarizer, beam_block)
  Mirror:             angle = (180 - α - β) / 2  mod 180
  Beam splitter:      angle = (270 - α - β) / 2  mod 180  (β = reflected arm)
  Dichroic:           same formula as beam splitter
  where α = incoming beam angle, β = outgoing/reflected beam angle
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .topology import BeamPathEdge, BeamPathSpec

_logger = logging.getLogger(__name__)

_DEG2RAD = math.pi / 180.0


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class PlacedComponent:
    """A component with computed position and orientation."""

    id: str
    library_id: str
    x_mm: float
    y_mm: float
    angle_deg: float
    overrides: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _direction(angle_deg: float) -> tuple[float, float]:
    """Unit direction vector for a user-convention angle."""
    rad = angle_deg * _DEG2RAD
    return (math.cos(rad), math.sin(rad))


def _normalize_angle(a: float) -> float:
    """Normalize angle to [0, 360)."""
    a = a % 360.0
    return a if a >= 0 else a + 360.0


def _interface_center(component_data: dict[str, Any], iface_idx: int = 0) -> tuple[float, float]:
    """
    Return the local-coord center of the given interface.

    component_data is raw component.json.  Interface coords are Y-up in the
    JSON but used as-is for Qt local coords (no Y-negation).
    """
    interfaces = component_data.get("interfaces", [])
    if not interfaces or iface_idx >= len(interfaces):
        return (0.0, 0.0)
    iface = interfaces[iface_idx]
    cx = (iface["x1_mm"] + iface["x2_mm"]) / 2.0
    cy = (iface["y1_mm"] + iface["y2_mm"]) / 2.0
    return (cx, cy)


def _rotated_offset(local_cx: float, local_cy: float, user_angle_deg: float) -> tuple[float, float]:
    """
    Compute the scene-space offset of a local point after the component is
    rotated by user_angle_deg (CW convention).

    Qt rotation matrix for qt_angle = -θ:
      [cos(θ)    sin(θ)]
      [-sin(θ)   cos(θ)]
    """
    rad = user_angle_deg * _DEG2RAD
    cos_t = math.cos(rad)
    sin_t = math.sin(rad)
    ox = local_cx * cos_t + local_cy * sin_t
    oy = -local_cx * sin_t + local_cy * cos_t
    return (ox, oy)


def _primary_element_type(component_data: dict[str, Any]) -> str | None:
    """Return the element_type of the first interface, or None."""
    interfaces = component_data.get("interfaces", [])
    if not interfaces:
        return None
    return interfaces[0].get("element_type")


def _is_source(library_id: str, component_data: dict[str, Any] | None) -> bool:
    """Heuristic: sources have category 'sources' or no interfaces."""
    if component_data is None:
        return library_id.startswith("source")
    cat = component_data.get("category", "")
    return cat == "sources" or not component_data.get("interfaces")


def _compute_orientation(
    element_type: str | None,
    incoming_angle: float | None,
    outgoing_angles: dict[str, float],
) -> float:
    """
    Compute the component angle_deg given its element type, the incoming beam
    angle, and a dict of {interaction: outgoing_angle}.
    """
    if incoming_angle is None:
        if outgoing_angles:
            return list(outgoing_angles.values())[0]
        return 0.0

    if element_type in ("mirror",):
        out_angle = list(outgoing_angles.values())[0] if outgoing_angles else incoming_angle + 180.0
        raw = (180.0 - incoming_angle - out_angle) / 2.0
        return _normalize_angle(raw % 180.0)

    if element_type in ("beam_splitter", "dichroic"):
        refl_angle = outgoing_angles.get("reflection")
        if refl_angle is None:
            refl_angle = outgoing_angles.get("transmission")
        if refl_angle is None:
            refl_angle = list(outgoing_angles.values())[0] if outgoing_angles else incoming_angle - 90.0
        raw = (270.0 - incoming_angle - refl_angle) / 2.0
        return _normalize_angle(raw % 180.0)

    return _normalize_angle(incoming_angle)


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def solve(
    spec: BeamPathSpec,
    catalog: dict[str, dict[str, Any]] | None = None,
) -> list[PlacedComponent]:
    """
    Solve a beam path spec into placed components.

    Algorithm:
      1. Build a graph of edges keyed by from_id and to_id.
      2. Identify source nodes (appear only as from_id, never as to_id).
      3. BFS from sources, propagating beam positions along edges.
      4. For each component, compute orientation from incoming/outgoing angles
         and apply interface-center offset correction.

    Args:
        spec: Beam path specification (topology).
        catalog: Optional pre-loaded catalog {library_id: component.json data}.
                 If None, loads from the default library directory.

    Returns:
        List of PlacedComponent with positions and orientations.
    """
    if catalog is None:
        from .catalog import scan_library
        catalog = scan_library()

    comp_map = {c.id: c for c in spec.components}

    outgoing: dict[str, list[BeamPathEdge]] = defaultdict(list)
    incoming: dict[str, list[BeamPathEdge]] = defaultdict(list)
    for edge in spec.beam_paths:
        outgoing[edge.from_id].append(edge)
        incoming[edge.to_id].append(edge)

    all_ids = {c.id for c in spec.components}
    source_ids = [
        c.id for c in spec.components
        if _is_source(c.library_id, catalog.get(c.library_id))
    ]
    if not source_ids:
        source_ids = list(all_ids - {e.to_id for e in spec.beam_paths})
    if not source_ids:
        raise ValueError("No source components found in beam path spec")

    # interface_pos[comp_id] = (x, y) where the beam hits the component
    interface_pos: dict[str, tuple[float, float]] = {}
    placed_angles: dict[str, float] = {}
    visit_order: list[str] = []

    queue: list[str] = []
    for i, sid in enumerate(source_ids):
        interface_pos[sid] = (0.0, i * 200.0)
        queue.append(sid)

    visited: set[str] = set()
    while queue:
        cid = queue.pop(0)
        if cid in visited:
            continue
        visited.add(cid)
        visit_order.append(cid)

        pos = interface_pos[cid]
        for edge in outgoing[cid]:
            dx, dy = _direction(edge.angle_deg)
            target_pos = (
                pos[0] + dx * edge.distance_mm,
                pos[1] + dy * edge.distance_mm,
            )
            tid = edge.to_id
            if tid not in interface_pos:
                interface_pos[tid] = target_pos
            if tid not in visited:
                queue.append(tid)

    for cid in visit_order:
        comp = comp_map[cid]
        cdata = catalog.get(comp.library_id)
        etype = _primary_element_type(cdata) if cdata else None

        in_angle: float | None = None
        for e in incoming[cid]:
            in_angle = e.angle_deg
            break

        out_map: dict[str, float] = {}
        for e in outgoing[cid]:
            interaction = e.interaction or "pass_through"
            out_map[interaction] = e.angle_deg

        if _is_source(comp.library_id, cdata):
            if out_map:
                angle = list(out_map.values())[0]
            else:
                angle = 0.0
        else:
            angle = _compute_orientation(etype, in_angle, out_map)

        placed_angles[cid] = angle

    result: list[PlacedComponent] = []
    for cid in visit_order:
        comp = comp_map[cid]
        angle = placed_angles[cid]
        ipos = interface_pos[cid]

        cdata = catalog.get(comp.library_id)
        cx, cy = _interface_center(cdata) if cdata else (0.0, 0.0)

        ox, oy = _rotated_offset(cx, cy, angle)
        comp_x = ipos[0] - ox
        comp_y = ipos[1] - oy

        result.append(PlacedComponent(
            id=comp.id,
            library_id=comp.library_id,
            x_mm=round(comp_x, 4),
            y_mm=round(comp_y, 4),
            angle_deg=round(_normalize_angle(angle), 4),
            overrides=comp.overrides,
        ))

    for c in spec.components:
        if c.id not in visited:
            _logger.warning("Component '%s' was not reached by beam propagation", c.id)
            result.append(PlacedComponent(
                id=c.id,
                library_id=c.library_id,
                x_mm=0.0,
                y_mm=0.0,
                angle_deg=0.0,
                overrides=c.overrides,
            ))

    return result
