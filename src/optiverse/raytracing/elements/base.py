"""
Base interface for all optical elements.

Defines the contract that all optical elements must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..ray import RayState


@dataclass
class RayIntersection:
    """
    Data structure for ray-element intersection information.
    """

    distance: float  # Distance from ray origin to hit point
    point: np.ndarray  # Hit point coordinates [x, y]
    tangent: np.ndarray  # Surface tangent at hit point (normalized)
    normal: np.ndarray  # Surface normal at hit point (normalized)
    center: np.ndarray  # Center point of the surface segment
    length: float  # Length of the surface segment
    interface: Optional[object] = None  # Optional: Reference to optical interface


class IOpticalElement(ABC):
    """
    Interface for all optical elements.

    This is the key to the polymorphic architecture. Each element type
    implements this interface, allowing the raytracing engine to work
    with any element without type checking.

    Design:
    - get_geometry() returns the line segment representing the element
    - interact() processes ray-element interaction
    - get_bounding_box() for spatial indexing (Phase 4)
    """

    @abstractmethod
    def get_geometry(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Get element geometry as line segment.

        Returns:
            Tuple of (p1, p2) where p1 and p2 are endpoints in mm
        """
        pass

    @abstractmethod
    def interact(
        self, ray: RayState, hit_point: np.ndarray, normal: np.ndarray, tangent: np.ndarray
    ) -> list[RayState]:
        """
        Process ray interaction with this element.

        This is the core method that implements optical physics.
        Each element type has its own physics.

        Args:
            ray: Incoming ray state
            hit_point: Intersection point in mm
            normal: Surface normal at hit point (normalized)
            tangent: Surface tangent at hit point (normalized)

        Returns:
            List of output rays (e.g., [transmitted, reflected])
            Empty list means ray was absorbed
        """
        pass

    def transform_q(
        self,
        q: complex,
        ray: RayState,
        normal: np.ndarray,
        *,
        hit_point: np.ndarray | None = None,
        tangent: np.ndarray | None = None,
    ) -> complex:
        """
        Transform the Gaussian beam q-parameter at this element.

        Default implementation returns q unchanged (identity transform).
        Override in subclasses that affect beam geometry (lenses, mirrors,
        refractive surfaces).

        Args:
            q: Complex beam parameter before interaction (after drift to the surface)
            ray: Incoming ray state (for direction, wavelength, etc.)
            normal: Surface normal at hit point
            hit_point: Intersection point (optional; used for lens height on aperture)
            tangent: Surface tangent at hit (optional; used with hit_point for lenses)

        Returns:
            Transformed q-parameter after interaction
        """
        return q

    @abstractmethod
    def get_bounding_box(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Get axis-aligned bounding box for spatial indexing.

        Returns:
            Tuple of (min_corner, max_corner) where each is [x, y] in mm
        """
        pass
