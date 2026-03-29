"""
Ray data structures for raytracing.

Pure data structures with no UI dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core.models import Polarization


@dataclass
class RayState:
    """
    Complete state of a ray during propagation.

    This is a pure data structure with no methods that modify state.
    Immutable pattern: methods return new RayState objects.
    """

    position: np.ndarray  # Current position [x, y] in mm
    direction: np.ndarray  # Normalized direction vector
    intensity: float  # Current intensity (0.0 to 1.0)
    polarization: Polarization  # Jones vector polarization state
    wavelength_nm: float  # Wavelength in nanometers
    path: list[np.ndarray] = field(
        default_factory=list
    )  # List of positions visited (deprecated, use path_points)
    events: int = 0  # Number of interactions so far
    # Additional fields for engine compatibility
    remaining_length: float = 1000.0  # Maximum remaining propagation length in mm
    base_rgb: tuple[int, int, int] = (220, 20, 60)  # Base color as RGB tuple
    path_points: list[np.ndarray] = field(default_factory=list)  # List of points for visualization
    path_polarizations: list = field(default_factory=list)  # Polarization at each path point
    path_intensities: list[float] = field(default_factory=list)  # Intensity at each path point
    q_parameter: complex | None = None  # Gaussian beam parameter (None = geometric)
    path_beam_radii: list[float] = field(default_factory=list)  # Beam radius per point (mm)

    def _copy_with(self, **overrides) -> RayState:
        """Create a copy of this RayState with specified field overrides."""
        return RayState(
            position=overrides.get("position", self.position),
            direction=overrides.get("direction", self.direction),
            intensity=overrides.get("intensity", self.intensity),
            polarization=overrides.get("polarization", self.polarization),
            wavelength_nm=overrides.get("wavelength_nm", self.wavelength_nm),
            path=overrides.get("path", self.path),
            events=overrides.get("events", self.events),
            remaining_length=overrides.get("remaining_length", self.remaining_length),
            base_rgb=overrides.get("base_rgb", self.base_rgb),
            path_points=overrides.get("path_points", self.path_points),
            path_polarizations=overrides.get("path_polarizations", self.path_polarizations),
            path_intensities=overrides.get("path_intensities", self.path_intensities),
            q_parameter=overrides.get("q_parameter", self.q_parameter),
            path_beam_radii=overrides.get("path_beam_radii", self.path_beam_radii),
        )

    def advance(self, distance: float) -> RayState:
        """
        Create new RayState advanced along direction by distance.

        Args:
            distance: Distance to advance in mm

        Returns:
            New RayState at advanced position
        """
        new_position = self.position + self.direction * distance
        return self._copy_with(
            position=new_position,
            path=self.path + [new_position],
        )

    def with_direction(self, new_direction: np.ndarray) -> RayState:
        """Create new RayState with different direction"""
        return self._copy_with(direction=new_direction)

    def with_intensity(self, new_intensity: float) -> RayState:
        """Create new RayState with different intensity"""
        return self._copy_with(intensity=new_intensity)

    def with_polarization(self, new_polarization: Polarization) -> RayState:
        """Create new RayState with different polarization"""
        return self._copy_with(polarization=new_polarization)

    def increment_events(self) -> RayState:
        """Create new RayState with events incremented"""
        return self._copy_with(events=self.events + 1)


@dataclass
class RayPath:
    """
    Complete path of a ray for visualization.

    This is the final output format from raytracing.
    """

    points: list[np.ndarray]  # Sequence of points along path
    rgba: tuple[int, int, int, int]  # Color with alpha (uses final intensity)
    polarization: Polarization  # Final polarization state
    wavelength_nm: float  # Wavelength in nanometers
    source_index: int = 0  # Index of the source that emitted this ray
    polarizations: list = field(default_factory=list)  # Per-point polarization states
    intensities: list[float] = field(default_factory=list)  # Per-point intensities (0.0 to 1.0)
    beam_radii: list[float] = field(default_factory=list)  # 1/e^2 beam radius in mm per point


# Alias for backward compatibility and simpler imports
Ray = RayState
