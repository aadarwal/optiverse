"""Reusable scoring utilities for traced ray paths."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

import numpy as np

from optiverse.raytracing.ray import RayPath

from .schema import ConstraintSpec, TargetSpec


def point_segment_distance(
    point: np.ndarray, a: np.ndarray, b: np.ndarray
) -> tuple[float, np.ndarray]:
    """Return the distance from a point to a segment and the closest point."""
    ab = b - a
    denom = float(np.dot(ab, ab))
    if denom <= 1e-12:
        return float(np.linalg.norm(point - a)), a
    t = max(0.0, min(1.0, float(np.dot(point - a, ab) / denom)))
    closest = a + t * ab
    return float(np.linalg.norm(point - closest)), closest


def path_length_mm(path: RayPath) -> float:
    """Return total polyline path length in millimeters."""
    if len(path.points) < 2:
        return 0.0
    return float(
        sum(
            np.linalg.norm(np.asarray(b, dtype=float) - np.asarray(a, dtype=float))
            for a, b in zip(path.points, path.points[1:], strict=False)
        )
    )


def polarization_overlap(path: RayPath, target_pol: str) -> float:
    """Return basis overlap for a final path polarization."""
    pol = path.polarization.normalize().jones_vector
    if target_pol == "horizontal":
        basis = np.array([1.0, 0.0], dtype=complex)
    elif target_pol == "vertical":
        basis = np.array([0.0, 1.0], dtype=complex)
    else:
        raise ValueError(f"Unsupported target polarization: {target_pol}")
    return float(abs(np.vdot(basis, pol)) ** 2)


def _closest_segment_to_target(
    path: RayPath, target: TargetSpec
) -> tuple[float, np.ndarray | None, int]:
    target_point = np.array([target.x_mm, target.y_mm], dtype=float)
    best_distance = float("inf")
    best_point = None
    best_segment_index = 0

    for index, (a, b) in enumerate(zip(path.points, path.points[1:], strict=False)):
        distance, closest = point_segment_distance(target_point, np.asarray(a), np.asarray(b))
        if distance < best_distance:
            best_distance = distance
            best_point = closest
            best_segment_index = index

    return best_distance, best_point, best_segment_index


def score_target(path: RayPath, target: TargetSpec) -> dict[str, Any]:
    """Score one path against one virtual target."""
    best_distance, best_point, best_segment_index = _closest_segment_to_target(path, target)
    intensity_index = min(best_segment_index + 1, max(0, len(path.intensities) - 1))
    intensity = float(path.intensities[intensity_index]) if path.intensities else 0.0
    overlap = polarization_overlap(path, target.polarization)

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


def _best_path_for_target(
    paths: list[RayPath], target: TargetSpec
) -> tuple[RayPath | None, dict[str, Any]]:
    if not paths:
        return None, {
            "hit": False,
            "closest_distance_mm": float("inf"),
            "closest_point_mm": None,
            "power_fraction": 0.0,
            "expected_power_fraction": target.expected_power_fraction,
            "power_error": abs(target.expected_power_fraction),
            "polarization": target.polarization,
            "polarization_overlap": 0.0,
            "path_index": None,
        }
    scored = [(index, path, score_target(path, target)) for index, path in enumerate(paths)]
    best_index, best_path, best_score = min(
        scored, key=lambda item: item[2]["closest_distance_mm"]
    )
    best_score["path_index"] = best_index
    return best_path, best_score


def serialize_ray_path(path: RayPath) -> dict[str, Any]:
    """Serialize a RayPath for reports."""
    return {
        "points_mm": [np.asarray(point).tolist() for point in path.points],
        "intensities": [float(value) for value in path.intensities],
        "path_element_ids": list(path.path_element_ids),
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


def _target_name(params: dict[str, Any]) -> str | None:
    value = params.get("target_name", params.get("target"))
    return str(value) if value is not None else None


def _selected_paths(
    paths: list[RayPath], targets_by_name: dict[str, TargetSpec], params: dict[str, Any]
) -> list[RayPath]:
    name = _target_name(params)
    if not name:
        return paths
    target = targets_by_name.get(name)
    if target is None:
        return []
    best_path, _score = _best_path_for_target(paths, target)
    return [best_path] if best_path is not None else []


def _first_present(params: dict[str, Any], *keys: str) -> Any:
    """Return the first present key's value. Caller guarantees one key exists."""
    for key in keys:
        if key in params:
            return params[key]
    raise KeyError(f"expected one of {keys} in params")


def _metric_pass(value: float, params: dict[str, Any], *, default_tolerance: float) -> bool:
    passed = True
    if "expected_mm" in params or "expected" in params:
        expected = float(_first_present(params, "expected_mm", "expected"))
        tolerance = float(params.get("tolerance_mm", params.get("tolerance", default_tolerance)))
        passed = passed and abs(value - expected) <= tolerance
    if "min_mm" in params or "min" in params:
        passed = passed and value >= float(_first_present(params, "min_mm", "min"))
    if "max_mm" in params or "max" in params:
        passed = passed and value <= float(_first_present(params, "max_mm", "max"))
    return passed


def _contains_elements(path: RayPath, expected: Iterable[str], *, ordered: bool) -> bool:
    expected_ids = [str(item) for item in expected]
    if not expected_ids:
        return True
    actual = [str(item) for item in path.path_element_ids]
    if not ordered:
        return set(expected_ids).issubset(actual)

    cursor = 0
    for element_id in actual:
        if element_id == expected_ids[cursor]:
            cursor += 1
            if cursor == len(expected_ids):
                return True
    return False


def _beam_radius_at_target(path: RayPath, target: TargetSpec) -> float | None:
    if not path.beam_radii:
        return None
    _distance, _point, segment_index = _closest_segment_to_target(path, target)
    radius_index = min(segment_index + 1, len(path.beam_radii) - 1)
    return float(path.beam_radii[radius_index])


def _segment_plane_crossing(
    a: np.ndarray, b: np.ndarray, *, axis_index: int, value_mm: float
) -> float | None:
    da = float(a[axis_index] - value_mm)
    db = float(b[axis_index] - value_mm)
    if abs(da) <= 1e-12:
        return 0.0
    if abs(db) <= 1e-12:
        return 1.0
    if da * db > 0:
        return None
    denom = float(b[axis_index] - a[axis_index])
    if abs(denom) <= 1e-12:
        return None
    t = float((value_mm - a[axis_index]) / denom)
    if 0.0 <= t <= 1.0:
        return t
    return None


def _spot_samples_at_plane(
    paths: list[RayPath], *, axis: str, value_mm: float
) -> tuple[list[np.ndarray], list[float]]:
    axis_index = 0 if axis == "x" else 1
    points: list[np.ndarray] = []
    weights: list[float] = []

    for path in paths:
        for segment_index, (a_raw, b_raw) in enumerate(
            zip(path.points, path.points[1:], strict=False)
        ):
            a = np.asarray(a_raw, dtype=float)
            b = np.asarray(b_raw, dtype=float)
            t = _segment_plane_crossing(a, b, axis_index=axis_index, value_mm=value_mm)
            if t is None:
                continue
            point = a + (b - a) * t
            intensity_index = min(segment_index + 1, max(0, len(path.intensities) - 1))
            weight = float(path.intensities[intensity_index]) if path.intensities else 1.0
            points.append(point)
            weights.append(max(weight, 0.0))
            break

    return points, weights


def _weighted_centroid(points: list[np.ndarray], weights: list[float]) -> np.ndarray:
    if not points:
        return np.array([math.nan, math.nan], dtype=float)
    point_array = np.asarray(points, dtype=float)
    weight_array = np.asarray(weights, dtype=float)
    if np.sum(weight_array) <= 1e-12:
        weight_array = np.ones(len(points), dtype=float)
    return np.asarray(np.average(point_array, axis=0, weights=weight_array), dtype=float)


def _score_constraint(
    constraint: ConstraintSpec,
    paths: list[RayPath],
    targets_by_name: dict[str, TargetSpec],
    target_scores: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    params = dict(constraint.params)
    kind = constraint.kind
    name = constraint.name or kind

    if kind == "target_hit":
        target = _target_name(params)
        score = target_scores.get(target or "", {})
        passed = bool(target and score.get("hit", False))
        return {
            "name": name,
            "kind": kind,
            "passed": passed,
            "target": target,
            "path_index": score.get("path_index"),
        }

    if kind == "power_at_target":
        target = _target_name(params)
        target_spec = targets_by_name.get(target or "")
        score = target_scores.get(target or "", {})
        power = float(score.get("power_fraction", 0.0))
        expected = float(
            params.get(
                "expected_power_fraction",
                params.get("expected", target_spec.expected_power_fraction if target_spec else 0.0),
            )
        )
        tolerance = float(params.get("tolerance", 1e-6))
        return {
            "name": name,
            "kind": kind,
            "passed": abs(power - expected) <= tolerance,
            "target": target,
            "path_index": score.get("path_index"),
            "power_fraction": power,
            "expected_power_fraction": expected,
            "power_error": abs(power - expected),
            "tolerance": tolerance,
        }

    if kind == "polarization_at_target":
        target = _target_name(params)
        target_spec = targets_by_name.get(target or "")
        path, selected_score = (
            _best_path_for_target(paths, target_spec)
            if target_spec is not None
            else (None, {})
        )
        polarization = str(
            params.get("polarization", target_spec.polarization if target_spec else "horizontal")
        )
        overlap = polarization_overlap(path, polarization) if path is not None else 0.0
        min_overlap = float(params.get("min_overlap", 0.99))
        return {
            "name": name,
            "kind": kind,
            "passed": overlap >= min_overlap,
            "target": target,
            "path_index": selected_score.get("path_index"),
            "polarization": polarization,
            "polarization_overlap": overlap,
            "min_overlap": min_overlap,
        }

    if kind == "branch_count":
        branch_count = len(paths)
        expected_count = params.get("expected", params.get("count"))
        passed = True if expected_count is None else branch_count == int(expected_count)
        return {
            "name": name,
            "kind": kind,
            "passed": passed,
            "diagnostic": True,
            "branch_count": branch_count,
            "expected": expected_count,
        }

    if kind == "path_contains_elements":
        expected = params.get("elements", [])
        selected = _selected_paths(paths, targets_by_name, params)
        ordered = bool(params.get("ordered", True))
        mode = str(params.get("mode", "any_path"))
        checks = [_contains_elements(path, expected, ordered=ordered) for path in selected]
        passed = all(checks) if mode == "all_paths" else any(checks)
        return {
            "name": name,
            "kind": kind,
            "passed": passed,
            "elements": list(expected),
            "ordered": ordered,
            "mode": mode,
            "matched_paths": sum(1 for check in checks if check),
            "checked_paths": len(checks),
        }

    if kind == "path_avoids_elements":
        avoided = {str(item) for item in params.get("elements", [])}
        selected = _selected_paths(paths, targets_by_name, params)
        checks = [avoided.isdisjoint(path.path_element_ids) for path in selected]
        passed = all(checks)
        return {
            "name": name,
            "kind": kind,
            "passed": passed,
            "elements": sorted(avoided),
            "checked_paths": len(checks),
        }

    if kind == "path_length":
        selected = _selected_paths(paths, targets_by_name, params)
        values = [path_length_mm(path) for path in selected]
        passed = bool(values) and all(
            _metric_pass(value, params, default_tolerance=1e-6) for value in values
        )
        return {
            "name": name,
            "kind": kind,
            "passed": passed,
            "path_lengths_mm": values,
        }

    if kind == "beam_radius_at_target":
        target = _target_name(params)
        target_spec = targets_by_name.get(target or "")
        path, selected_score = (
            _best_path_for_target(paths, target_spec)
            if target_spec is not None
            else (None, {})
        )
        radius = (
            _beam_radius_at_target(path, target_spec)
            if path is not None and target_spec is not None
            else None
        )
        passed = radius is not None and _metric_pass(radius, params, default_tolerance=1e-6)
        return {
            "name": name,
            "kind": kind,
            "passed": passed,
            "target": target,
            "path_index": selected_score.get("path_index"),
            "beam_radius_mm": radius,
            "unsupported": radius is None,
            "warnings": (
                ["No Gaussian beam radius data on selected path"] if radius is None else []
            ),
        }

    if kind in {"spot_centroid_at_plane", "spot_rms_radius_at_plane"}:
        axis = str(params.get("axis", "x")).lower()
        if axis not in {"x", "y"}:
            raise ValueError(f"Unsupported plane axis: {axis}")
        value_mm = float(_first_present(params, "value_mm", f"{axis}_mm"))
        selected = _selected_paths(paths, targets_by_name, params)
        samples, weights = _spot_samples_at_plane(selected, axis=axis, value_mm=value_mm)
        centroid = _weighted_centroid(samples, weights)

        if kind == "spot_centroid_at_plane":
            errors = []
            if "expected_x_mm" in params:
                errors.append(float(centroid[0] - float(params["expected_x_mm"])))
            if "expected_y_mm" in params:
                errors.append(float(centroid[1] - float(params["expected_y_mm"])))
            error = math.sqrt(sum(item * item for item in errors)) if errors else 0.0
            tolerance = float(params.get("tolerance_mm", params.get("tolerance", 1e-6)))
            passed = bool(samples) and (not errors or error <= tolerance)
            return {
                "name": name,
                "kind": kind,
                "passed": passed,
                "axis": axis,
                "value_mm": value_mm,
                "sample_count": len(samples),
                "centroid_mm": centroid.tolist(),
                "centroid_error_mm": error,
                "tolerance_mm": tolerance,
            }

        center = centroid.copy()
        if "expected_x_mm" in params:
            center[0] = float(params["expected_x_mm"])
        if "expected_y_mm" in params:
            center[1] = float(params["expected_y_mm"])
        point_array = np.asarray(samples, dtype=float)
        weight_array = np.asarray(weights, dtype=float)
        if len(point_array) == 0:
            rms = math.inf
        else:
            if np.sum(weight_array) <= 1e-12:
                weight_array = np.ones(len(point_array), dtype=float)
            radii2 = np.sum((point_array - center) ** 2, axis=1)
            rms = float(math.sqrt(np.average(radii2, weights=weight_array)))
        passed = math.isfinite(rms) and _metric_pass(rms, params, default_tolerance=1e-6)
        return {
            "name": name,
            "kind": kind,
            "passed": passed,
            "axis": axis,
            "value_mm": value_mm,
            "sample_count": len(samples),
            "centroid_mm": centroid.tolist(),
            "spot_rms_radius_mm": rms,
        }

    return {
        "name": name,
        "kind": kind,
        "passed": False,
        "error": f"Unsupported constraint kind: {kind}",
    }


def score_constraints(
    paths: list[RayPath], targets: list[TargetSpec], constraints: list[ConstraintSpec]
) -> list[dict[str, Any]]:
    """Score generic constraints against traced paths."""
    targets_by_name = {target.name: target for target in targets}
    target_scores = {}
    for target in targets:
        _path, score = _best_path_for_target(paths, target)
        target_scores[target.name] = score
    return [
        _score_constraint(constraint, paths, targets_by_name, target_scores)
        for constraint in constraints
    ]


def score_paths(
    paths: list[RayPath],
    targets: list[TargetSpec],
    constraints: list[ConstraintSpec] | None = None,
) -> dict[str, Any]:
    """Score paths against all targets."""
    target_scores = {}
    for target in targets:
        _path, best = _best_path_for_target(paths, target)
        target_scores[target.name] = best

    constraint_scores = score_constraints(paths, targets, constraints or [])
    target_passed = all(score["hit"] for score in target_scores.values()) and all(
        score["polarization_overlap"] > 0.99 for score in target_scores.values()
    ) and all(score["power_error"] < 1e-6 for score in target_scores.values())
    constraints_passed = all(score["passed"] for score in constraint_scores)

    return {
        "target_scores": target_scores,
        "constraint_scores": constraint_scores,
        "passed": target_passed and constraints_passed,
        "ray_paths": [serialize_ray_path(path) for path in paths],
    }
