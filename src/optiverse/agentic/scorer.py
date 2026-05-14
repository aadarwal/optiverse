"""Reusable scoring utilities for traced ray paths."""

from __future__ import annotations

from typing import Any

import numpy as np

from optiverse.raytracing.ray import RayPath

from .schema import TargetSpec


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


def score_target(path: RayPath, target: TargetSpec) -> dict[str, Any]:
    """Score one path against one virtual target."""
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


def serialize_ray_path(path: RayPath) -> dict[str, Any]:
    """Serialize a RayPath for reports."""
    return {
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


def score_paths(paths: list[RayPath], targets: list[TargetSpec]) -> dict[str, Any]:
    """Score paths against all targets."""
    target_scores = {}
    for target in targets:
        scores = [score_target(path, target) for path in paths]
        best = min(scores, key=lambda item: item["closest_distance_mm"])
        target_scores[target.name] = best

    return {
        "target_scores": target_scores,
        "passed": all(score["hit"] for score in target_scores.values())
        and all(score["polarization_overlap"] > 0.99 for score in target_scores.values())
        and all(score["power_error"] < 1e-6 for score in target_scores.values()),
        "ray_paths": [serialize_ray_path(path) for path in paths],
    }
