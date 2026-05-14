"""Pre-raytrace validation for headless agentic layout plans."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .catalog import Catalog
from .scene_writer import build_scene_data
from .schema import ConstraintSpec, GoalSpec, Placement, SourceSpec


@dataclass(frozen=True)
class TableRect:
    """Axis-aligned table bounds in millimeters."""

    x_min_mm: float
    y_min_mm: float
    x_max_mm: float
    y_max_mm: float

    @classmethod
    def from_tuple(cls, values: tuple[float, float, float, float]) -> TableRect:
        return cls(*values)


@dataclass(frozen=True)
class ValidationIssue:
    """One validation issue."""

    severity: str
    code: str
    message: str
    field: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult:
    """Validation issues plus aggregate status."""

    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors

    def add_error(self, code: str, message: str, field: str | None = None) -> None:
        self.issues.append(ValidationIssue("error", code, message, field))

    def add_warning(self, code: str, message: str, field: str | None = None) -> None:
        self.issues.append(ValidationIssue("warning", code, message, field))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
        }


KNOWN_CONSTRAINT_KINDS = {
    "target_hit",
    "power_at_target",
    "polarization_at_target",
    "branch_count",
    "path_contains_elements",
    "path_avoids_elements",
    "path_length",
    "beam_radius_at_target",
    "spot_centroid_at_plane",
    "spot_rms_radius_at_plane",
}

BASE_INTERFACE_OVERRIDE_FIELDS = {
    "x1_mm",
    "y1_mm",
    "x2_mm",
    "y2_mm",
    "element_type",
    "radius_of_curvature_mm",
}

INTERFACE_OVERRIDE_FIELDS = {
    "lens": {"efl_mm", "clear_aperture_mm"},
    "mirror": {"reflectivity"},
    "beam_splitter": {"split_T", "split_R", "is_polarizing", "pbs_transmission_axis_deg"},
    "beamsplitter": {"split_T", "split_R", "is_polarizing", "pbs_transmission_axis_deg"},
    "dichroic": {"cutoff_wavelength_nm", "transition_width_nm", "pass_type"},
    "polarizing_interface": {
        "polarizer_subtype",
        "phase_shift_deg",
        "fast_axis_deg",
        "transmission_axis_deg",
        "extinction_ratio_db",
        "rotation_angle_deg",
    },
    "faraday_rotator": {"rotation_angle_deg"},
    "linear_polarizer": {"transmission_axis_deg", "extinction_ratio_db"},
    "beam_block": set(),
}


def _is_finite(value: object) -> bool:
    return isinstance(value, int | float) and math.isfinite(float(value))


def _numeric_field_valid(value: object, *, minimum: float | None = None) -> bool:
    if not _is_finite(value):
        return False
    return minimum is None or float(value) >= minimum


def _placement_footprint(
    catalog: Catalog, placement: Placement, clearance_mm: float
) -> tuple[float, float, float, float] | None:
    component = catalog.get(placement.catalog_id)
    if component is None:
        return None
    object_height = component.get("object_height_mm", 0.0)
    if not _numeric_field_valid(object_height, minimum=0.0):
        return None
    half = 0.5 * float(object_height) + clearance_mm
    return (
        placement.x_mm - half,
        placement.y_mm - half,
        placement.x_mm + half,
        placement.y_mm + half,
    )


def _boxes_overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _box_within_table(box: tuple[float, float, float, float], table: TableRect) -> bool:
    return (
        box[0] >= table.x_min_mm
        and box[1] >= table.y_min_mm
        and box[2] <= table.x_max_mm
        and box[3] <= table.y_max_mm
    )


def _allowed_override_fields(iface: dict[str, Any]) -> set[str]:
    element_type = str(iface.get("element_type", "")).lower()
    return (
        BASE_INTERFACE_OVERRIDE_FIELDS
        | set(iface.keys())
        | INTERFACE_OVERRIDE_FIELDS.get(element_type, set())
    )


def _validate_source(source: SourceSpec, result: ValidationResult) -> None:
    numeric_fields = {
        "source.x_mm": source.x_mm,
        "source.y_mm": source.y_mm,
        "source.angle_deg": source.angle_deg,
        "source.size_mm": source.size_mm,
        "source.ray_length_mm": source.ray_length_mm,
        "source.spread_deg": source.spread_deg,
        "source.wavelength_nm": source.wavelength_nm,
    }
    for field_name, value in numeric_fields.items():
        if not _is_finite(value):
            result.add_error("invalid_source_field", f"{field_name} must be finite", field_name)

    if source.n_rays < 1:
        result.add_error("invalid_source_field", "source.n_rays must be >= 1", "source.n_rays")
    if source.size_mm < 0:
        result.add_error("invalid_source_field", "source.size_mm must be >= 0", "source.size_mm")
    if source.ray_length_mm <= 0:
        result.add_error(
            "invalid_source_field",
            "source.ray_length_mm must be > 0",
            "source.ray_length_mm",
        )
    if source.wavelength_nm <= 0:
        result.add_error(
            "invalid_source_field",
            "source.wavelength_nm must be > 0",
            "source.wavelength_nm",
        )
    if source.source_type not in {"ray", "gaussian"}:
        result.add_error(
            "invalid_source_field",
            "source.source_type must be 'ray' or 'gaussian'",
            "source.source_type",
        )
    if source.source_type == "gaussian" and source.beam_waist_mm <= 0:
        result.add_error(
            "invalid_source_field",
            "source.beam_waist_mm must be > 0 for gaussian sources",
            "source.beam_waist_mm",
        )


def _validate_placement(
    catalog: Catalog,
    placement: Placement,
    index: int,
    result: ValidationResult,
) -> None:
    field_prefix = f"placements[{index}]"
    if placement.catalog_id not in catalog:
        result.add_error(
            "unknown_catalog_id",
            f"Unknown catalog_id '{placement.catalog_id}'",
            f"{field_prefix}.catalog_id",
        )
        return

    for field_name, value in {
        "x_mm": placement.x_mm,
        "y_mm": placement.y_mm,
        "angle_deg": placement.angle_deg,
    }.items():
        if not _is_finite(value):
            result.add_error(
                "invalid_placement_field",
                f"{field_prefix}.{field_name} must be finite",
                f"{field_prefix}.{field_name}",
            )

    interfaces = catalog[placement.catalog_id].get("interfaces", []) or []
    if not interfaces:
        result.add_error(
            "missing_interfaces",
            f"{placement.catalog_id} has no optical interfaces",
            f"{field_prefix}.catalog_id",
        )

    for override_index, overrides in placement.normalized_overrides().items():
        override_field = f"{field_prefix}.interface_overrides[{override_index}]"
        if override_index < 0 or override_index >= len(interfaces):
            result.add_error(
                "invalid_override_index",
                f"Override index {override_index} does not exist on {placement.catalog_id}",
                override_field,
            )
            continue

        allowed_fields = _allowed_override_fields(interfaces[override_index])
        for key, value in overrides.items():
            if key not in allowed_fields:
                result.add_error(
                    "invalid_override_field",
                    f"Override field '{key}' is not valid for interface {override_index}",
                    f"{override_field}.{key}",
                )
            if isinstance(value, int | float) and not math.isfinite(float(value)):
                result.add_error(
                    "invalid_override_value",
                    f"Override field '{key}' must be finite",
                    f"{override_field}.{key}",
                )


def _validate_targets(goal: GoalSpec, result: ValidationResult) -> set[str]:
    target_names: set[str] = set()
    for index, target in enumerate(goal.targets):
        field_prefix = f"targets[{index}]"
        if target.name in target_names:
            result.add_error("duplicate_target", f"Duplicate target '{target.name}'", field_prefix)
        target_names.add(target.name)

        for field_name, value in {
            "x_mm": target.x_mm,
            "y_mm": target.y_mm,
            "radius_mm": target.radius_mm,
            "expected_power_fraction": target.expected_power_fraction,
        }.items():
            if not _is_finite(value):
                result.add_error(
                    "invalid_target_field",
                    f"{field_prefix}.{field_name} must be finite",
                    f"{field_prefix}.{field_name}",
                )
        if target.radius_mm <= 0:
            result.add_error(
                "invalid_target_field",
                f"{field_prefix}.radius_mm must be > 0",
                f"{field_prefix}.radius_mm",
            )
        if not 0 <= target.expected_power_fraction <= 1:
            result.add_error(
                "invalid_target_field",
                f"{field_prefix}.expected_power_fraction must be between 0 and 1",
                f"{field_prefix}.expected_power_fraction",
            )

    return target_names


def _validate_constraint_target(
    constraint: ConstraintSpec, target_names: set[str], result: ValidationResult, index: int
) -> None:
    target = constraint.params.get("target", constraint.params.get("target_name"))
    if target is not None and str(target) not in target_names:
        result.add_error(
            "unknown_constraint_target",
            f"Constraint target '{target}' is not defined",
            f"constraints[{index}].params.target",
        )


def _validate_constraints(
    constraints: list[ConstraintSpec], target_names: set[str], result: ValidationResult
) -> None:
    for index, constraint in enumerate(constraints):
        field_prefix = f"constraints[{index}]"
        if constraint.kind not in KNOWN_CONSTRAINT_KINDS:
            result.add_warning(
                "unknown_constraint_kind",
                f"Unknown constraint kind '{constraint.kind}'",
                f"{field_prefix}.kind",
            )

        _validate_constraint_target(constraint, target_names, result, index)

        for key in ("tolerance", "tolerance_mm"):
            if key in constraint.params and not _numeric_field_valid(
                constraint.params[key], minimum=0.0
            ):
                result.add_error(
                    "invalid_constraint_tolerance",
                    f"{field_prefix}.params.{key} must be finite and >= 0",
                    f"{field_prefix}.params.{key}",
                )

        if constraint.kind in {"path_contains_elements", "path_avoids_elements"}:
            elements = constraint.params.get("elements")
            if not isinstance(elements, list):
                result.add_error(
                    "invalid_constraint_elements",
                    f"{field_prefix}.params.elements must be a list",
                    f"{field_prefix}.params.elements",
                )

        if constraint.kind in {"spot_centroid_at_plane", "spot_rms_radius_at_plane"}:
            axis = str(constraint.params.get("axis", "x")).lower()
            if axis not in {"x", "y"}:
                result.add_error(
                    "invalid_constraint_axis",
                    f"{field_prefix}.params.axis must be 'x' or 'y'",
                    f"{field_prefix}.params.axis",
                )
            if "value_mm" not in constraint.params and f"{axis}_mm" not in constraint.params:
                result.add_error(
                    "missing_constraint_plane",
                    f"{field_prefix} must define value_mm or {axis}_mm",
                    f"{field_prefix}.params.value_mm",
                )


def _validate_footprints(
    goal: GoalSpec,
    catalog: Catalog,
    result: ValidationResult,
    *,
    table_rect: TableRect | None,
    clearance_mm: float,
) -> None:
    footprints: list[tuple[int, Placement, tuple[float, float, float, float]]] = []
    for index, placement in enumerate(goal.placements):
        footprint = _placement_footprint(catalog, placement, clearance_mm)
        if footprint is None:
            continue
        footprints.append((index, placement, footprint))

        if table_rect is not None and not _box_within_table(footprint, table_rect):
            result.add_error(
                "placement_out_of_bounds",
                f"Placement '{placement.label}' is outside table bounds",
                f"placements[{index}]",
            )

    for left_index, left_placement, left_box in footprints:
        for right_index, right_placement, right_box in footprints:
            if right_index <= left_index:
                continue
            if _boxes_overlap(left_box, right_box):
                result.add_error(
                    "footprint_overlap",
                    f"Placements '{left_placement.label}' and '{right_placement.label}' overlap",
                    f"placements[{left_index}],placements[{right_index}]",
                )


def validate_goal(
    goal: GoalSpec,
    catalog: Catalog,
    *,
    table_rect: TableRect | tuple[float, float, float, float] | None = None,
    clearance_mm: float = 0.0,
) -> ValidationResult:
    """Validate a goal before compiling or raytracing it."""
    result = ValidationResult()
    table = TableRect.from_tuple(table_rect) if isinstance(table_rect, tuple) else table_rect

    _validate_source(goal.source, result)
    for index, placement in enumerate(goal.placements):
        _validate_placement(catalog, placement, index, result)
    target_names = _validate_targets(goal, result)
    _validate_constraints(goal.constraints, target_names, result)
    _validate_footprints(
        goal,
        catalog,
        result,
        table_rect=table,
        clearance_mm=max(0.0, float(clearance_mm)),
    )

    try:
        build_scene_data(catalog, goal)
    except Exception as exc:  # pragma: no cover - defensive integration guard
        result.add_error("scene_generation_failed", str(exc), "scene")

    return result
