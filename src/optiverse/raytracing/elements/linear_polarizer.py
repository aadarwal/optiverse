"""
Linear polarizer element implementation.

Transmits the component of light polarized along its transmission axis
and attenuates the orthogonal component according to the extinction ratio.
"""

import numpy as np

from ...core.raytracing_math import (
    normalize,
    transform_polarization_linear_polarizer,
)
from ..ray import RayState
from .base import IOpticalElement


class LinearPolarizerElement(IOpticalElement):
    """
    Linear polarizer element with configurable transmission axis and extinction ratio.

    Implements Malus's Law: I_out = I_in * cos²(θ), where θ is the angle
    between the input polarization and the transmission axis.

    The extinction axis is perpendicular to the transmission axis.
    A finite extinction ratio allows a small fraction of the blocked
    component to leak through (e.g. 40 dB = 10,000:1 rejection).
    """

    def __init__(
        self,
        p1: np.ndarray,
        p2: np.ndarray,
        transmission_axis_deg: float,
        extinction_ratio_db: float = 40.0,
    ):
        """
        Initialize linear polarizer element.

        Args:
            p1: Start point of element line segment [x, y] in mm
            p2: End point of element line segment [x, y] in mm
            transmission_axis_deg: Transmission axis angle in lab frame (degrees)
            extinction_ratio_db: Extinction ratio in dB (40 dB = 10,000:1)
        """
        self.p1 = np.array(p1, dtype=float)
        self.p2 = np.array(p2, dtype=float)
        self.transmission_axis_deg = transmission_axis_deg
        self.extinction_ratio_db = extinction_ratio_db

    def get_geometry(self) -> tuple[np.ndarray, np.ndarray]:
        """Get element line segment."""
        return self.p1, self.p2

    def interact(
        self, ray: RayState, hit_point: np.ndarray, normal: np.ndarray, tangent: np.ndarray
    ) -> list[RayState]:
        """
        Apply linear polarizer to ray.

        Physics:
        - Projects polarization onto transmission axis (Malus's Law)
        - Attenuates orthogonal component by extinction ratio
        - Ray direction unchanged (polarizer doesn't deflect ray)
        - Intensity reduced according to projection
        """
        polarization_out, intensity_factor = transform_polarization_linear_polarizer(
            ray.polarization, self.transmission_axis_deg, self.extinction_ratio_db
        )

        new_intensity = ray.intensity * intensity_factor

        # If intensity is essentially zero, the ray is extinguished
        if new_intensity < 1e-12:
            return []

        # Ray continues in same direction with transformed polarization
        EPS_ADV = 1e-3
        direction_out = normalize(ray.direction)

        output_ray = RayState(
            position=hit_point + direction_out * EPS_ADV,
            direction=direction_out,
            intensity=new_intensity,
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
