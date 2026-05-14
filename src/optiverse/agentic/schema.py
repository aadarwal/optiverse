"""Serializable schemas for the headless agentic layout harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from optiverse.core.models import SourceParams


@dataclass(frozen=True)
class SourceSpec:
    """Serializable light source specification."""

    x_mm: float = 0.0
    y_mm: float = 0.0
    angle_deg: float = 0.0
    size_mm: float = 0.0
    n_rays: int = 1
    ray_length_mm: float = 500.0
    spread_deg: float = 0.0
    color_hex: str = "#DC143C"
    wavelength_nm: float = 780.0
    polarization_type: str = "horizontal"
    polarization_angle_deg: float = 0.0
    custom_jones_ex_real: float = 1.0
    custom_jones_ex_imag: float = 0.0
    custom_jones_ey_real: float = 0.0
    custom_jones_ey_imag: float = 0.0
    use_custom_jones: bool = False
    source_type: str = "ray"
    beam_waist_mm: float = 0.5

    def to_source_params(self) -> SourceParams:
        return SourceParams(**asdict(self))

    @classmethod
    def from_source_params(cls, source: SourceParams) -> SourceSpec:
        values = {
            field_name: getattr(source, field_name)
            for field_name in cls.__dataclass_fields__
        }
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceSpec:
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass(frozen=True)
class Placement:
    """A component selected from the catalog and placed on the table."""

    label: str
    catalog_id: str
    x_mm: float
    y_mm: float
    angle_deg: float = 0.0
    interface_overrides: dict[int, dict[str, Any]] | None = None

    def normalized_overrides(self) -> dict[int, dict[str, Any]]:
        if not self.interface_overrides:
            return {}
        return {int(index): dict(values) for index, values in self.interface_overrides.items()}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.interface_overrides:
            data["interface_overrides"] = {
                str(index): values for index, values in self.interface_overrides.items()
            }
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Placement:
        overrides = data.get("interface_overrides")
        if isinstance(overrides, dict):
            overrides = {int(index): dict(values) for index, values in overrides.items()}
        return cls(
            label=str(data["label"]),
            catalog_id=str(data["catalog_id"]),
            x_mm=float(data["x_mm"]),
            y_mm=float(data["y_mm"]),
            angle_deg=float(data.get("angle_deg", 0.0)),
            interface_overrides=overrides,
        )


@dataclass(frozen=True)
class TargetSpec:
    """Virtual detector target used for scoring traced paths."""

    name: str
    x_mm: float
    y_mm: float
    radius_mm: float
    polarization: str
    expected_power_fraction: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetSpec:
        return cls(
            name=str(data["name"]),
            x_mm=float(data["x_mm"]),
            y_mm=float(data["y_mm"]),
            radius_mm=float(data["radius_mm"]),
            polarization=str(data["polarization"]),
            expected_power_fraction=float(data["expected_power_fraction"]),
        )


@dataclass(frozen=True)
class ConstraintSpec:
    """Small generic constraint container; specialized constraints arrive in Milestone 2."""

    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoalSpec:
    """A full explicit-placement goal for the current headless harness."""

    goal_id: str
    description: str
    source: SourceSpec
    placements: list[Placement]
    targets: list[TargetSpec] = field(default_factory=list)
    constraints: list[ConstraintSpec] = field(default_factory=list)
    topology: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "source": self.source.to_dict(),
            "placements": [placement.to_dict() for placement in self.placements],
            "targets": [target.to_dict() for target in self.targets],
            "constraints": [constraint.to_dict() for constraint in self.constraints],
            "topology": self.topology,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoalSpec:
        return cls(
            goal_id=str(data["goal_id"]),
            description=str(data["description"]),
            source=SourceSpec.from_dict(data["source"]),
            placements=[Placement.from_dict(item) for item in data.get("placements", [])],
            targets=[TargetSpec.from_dict(item) for item in data.get("targets", [])],
            constraints=[
                ConstraintSpec(
                    kind=str(item["kind"]),
                    params=dict(item.get("params", {})),
                    name=item.get("name"),
                )
                for item in data.get("constraints", [])
            ],
            topology=str(data.get("topology", "")),
        )


@dataclass(frozen=True)
class RunResult:
    """Serializable output from one headless agentic layout run."""

    goal: GoalSpec
    score: dict[str, Any]
    output_files: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal.to_dict(),
            "score": self.score,
            "output_files": dict(self.output_files),
        }


def demo_goal_spec() -> GoalSpec:
    """Return the HWP/PBS splitter goal from the original proof-of-concept."""
    description = (
        "Take a 780 nm horizontally polarized source, rotate it with an HWP so a PBS "
        "splits it 50/50, send H to D1 and V to D2."
    )
    return GoalSpec(
        goal_id="agentic_hwp_pbs",
        description=description,
        topology="source -> HWP1 -> PBS1 -> {transmitted: D1, reflected: D2}",
        source=SourceSpec(),
        placements=[
            Placement(
                label="HWP1",
                catalog_id="waveplate_hwp",
                x_mm=60.0,
                y_mm=0.0,
                interface_overrides={0: {"fast_axis_deg": 22.5}},
            ),
            Placement(label="PBS1", catalog_id="pbs_2in", x_mm=145.0, y_mm=0.0),
        ],
        targets=[
            TargetSpec(
                name="D1_transmitted_H",
                x_mm=300.0,
                y_mm=0.0,
                radius_mm=2.0,
                polarization="horizontal",
                expected_power_fraction=0.5,
            ),
            TargetSpec(
                name="D2_reflected_V",
                x_mm=145.0,
                y_mm=-250.0,
                radius_mm=2.0,
                polarization="vertical",
                expected_power_fraction=0.5,
            ),
        ],
    )
