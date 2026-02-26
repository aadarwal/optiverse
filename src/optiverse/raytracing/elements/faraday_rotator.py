"""
Faraday rotator element implementation.

Non-reciprocal polarization rotation via the magneto-optic Faraday effect.
"""

import math

import numpy as np

from ...core.raytracing_math import (
    deg2rad,
    normalize,
    transform_polarization_faraday_rotator,
)
from ..ray import RayState
from .base import IOpticalElement


class FaradayRotatorElement(IOpticalElement):
    """
    Faraday rotator element with configurable rotation angle.

    Rotates the polarization plane by a fixed angle in the same absolute
    direction regardless of propagation direction (non-reciprocal).

    A 45-degree Faraday rotator combined with a mirror gives 90-degree
    total rotation (basis of optical isolators).
    """

    def __init__(
        self,
        p1: np.ndarray,
        p2: np.ndarray,
        rotation_angle_deg: float,
        element_angle_deg: float = 90.0,
    ):
        """
        Initialize Faraday rotator element.

        Args:
            p1: Start point of element line segment [x, y] in mm
            p2: End point of element line segment [x, y] in mm
            rotation_angle_deg: Rotation angle in degrees (typically 45.0)
            element_angle_deg: Orientation angle of element for directionality (degrees)
        """
        self.p1 = np.array(p1, dtype=float)
        self.p2 = np.array(p2, dtype=float)
        self.rotation_angle_deg = rotation_angle_deg
        self.element_angle_deg = element_angle_deg

    def get_geometry(self) -> tuple[np.ndarray, np.ndarray]:
        """Get element line segment."""
        return self.p1, self.p2

    def interact(
        self, ray: RayState, hit_point: np.ndarray, normal: np.ndarray, tangent: np.ndarray
    ) -> list[RayState]:
        """
        Apply Faraday rotation to polarization.

        Physics:
        - Rotates polarization plane by rotation_angle_deg
        - Non-reciprocal: same rotation for forward and backward propagation
        - Ray direction unchanged (Faraday rotator doesn't deflect ray)
        """
        # Determine forward/backward direction (same pattern as waveplate)
        element_angle_rad = deg2rad(self.element_angle_deg)
        forward_normal = np.array([-math.sin(element_angle_rad), math.cos(element_angle_rad)])
        dot_v_n = float(np.dot(ray.direction, forward_normal))
        is_forward = dot_v_n < 0

        # Apply Faraday rotation (is_forward is passed but has no effect — non-reciprocal)
        polarization_out = transform_polarization_faraday_rotator(
            ray.polarization, self.rotation_angle_deg, is_forward
        )

        # Ray continues in same direction with transformed polarization
        EPS_ADV = 1e-3
        direction_out = normalize(ray.direction)

        output_ray = RayState(
            position=hit_point + direction_out * EPS_ADV,
            direction=direction_out,
            intensity=ray.intensity,  # No loss in ideal Faraday rotator
            polarization=polarization_out,
            wavelength_nm=ray.wavelength_nm,
            path=ray.path + [hit_point],
            events=ray.events + 1,
        )

        return [output_ray]

    def get_bounding_box(self) -> tuple[np.ndarray, np.ndarray]:
        """Get axis-aligned bounding box."""
        min_corner = np.minimum(self.p1, self.p2)
        max_corner = np.maximum(self.p1, self.p2)
        return min_corner, max_corner
