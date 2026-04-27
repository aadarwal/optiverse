"""Beam path specification dataclasses and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComponentSpec:
    """A component in the beam path specification."""

    id: str
    library_id: str
    overrides: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComponentSpec:
        return cls(
            id=data["id"],
            library_id=data["library_id"],
            overrides=data.get("overrides", {}),
        )


@dataclass
class BeamPathEdge:
    """A beam segment connecting two components."""

    from_id: str
    to_id: str
    angle_deg: float
    distance_mm: float
    interaction: str = "pass_through"
    reason: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BeamPathEdge:
        return cls(
            from_id=data["from"],
            to_id=data["to"],
            angle_deg=float(data["angle_deg"]),
            distance_mm=float(data["distance_mm"]),
            interaction=data.get("interaction", "pass_through"),
            reason=data.get("reason", ""),
        )


@dataclass
class BeamPathSpec:
    """Complete beam path specification produced by the LLM."""

    components: list[ComponentSpec]
    beam_paths: list[BeamPathEdge]
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BeamPathSpec:
        components = [ComponentSpec.from_dict(c) for c in data["components"]]
        beam_paths = [BeamPathEdge.from_dict(e) for e in data["beam_paths"]]
        return cls(
            components=components,
            beam_paths=beam_paths,
            description=data.get("description", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.description:
            result["description"] = self.description
        result["components"] = []
        for c in self.components:
            entry: dict[str, Any] = {"id": c.id, "library_id": c.library_id}
            if c.overrides:
                entry["overrides"] = c.overrides
            result["components"].append(entry)
        result["beam_paths"] = []
        for e in self.beam_paths:
            entry = {
                "from": e.from_id,
                "to": e.to_id,
                "angle_deg": e.angle_deg,
                "distance_mm": e.distance_mm,
            }
            if e.interaction != "pass_through":
                entry["interaction"] = e.interaction
            if e.reason:
                entry["reason"] = e.reason
            result["beam_paths"].append(entry)
        return result


def validate_spec(spec: BeamPathSpec, available_library_ids: set[str]) -> list[str]:
    """Validate a beam path spec. Returns list of error messages (empty = valid)."""
    errors: list[str] = []

    component_ids = {c.id for c in spec.components}
    if len(component_ids) != len(spec.components):
        errors.append("Duplicate component IDs found")

    for c in spec.components:
        if c.library_id not in available_library_ids:
            errors.append(f"Unknown library_id '{c.library_id}' for component '{c.id}'")

    for edge in spec.beam_paths:
        if edge.from_id not in component_ids:
            errors.append(f"beam_path references unknown component '{edge.from_id}'")
        if edge.to_id not in component_ids:
            errors.append(f"beam_path references unknown component '{edge.to_id}'")
        if edge.distance_mm <= 0:
            errors.append(
                f"beam_path {edge.from_id}->{edge.to_id} has non-positive distance"
            )

    sources = {e.from_id for e in spec.beam_paths} - {e.to_id for e in spec.beam_paths}
    if not sources:
        errors.append("No source component found (no component is only a 'from' in beam_paths)")

    reachable = set(sources)
    changed = True
    while changed:
        changed = False
        for edge in spec.beam_paths:
            if edge.from_id in reachable and edge.to_id not in reachable:
                reachable.add(edge.to_id)
                changed = True
    unreachable = component_ids - reachable
    for cid in unreachable:
        comp = next(c for c in spec.components if c.id == cid)
        if comp.library_id not in ("laser_table", "breadboard_mbh24"):
            errors.append(f"Component '{cid}' is not reachable from any source via beam_paths")

    return errors
