"""Ray path rendering for the UI.

This module handles the visual rendering of traced ray paths to the scene,
using either OpenGL hardware acceleration or software fallback.

Each source's rays are rendered at the source's z-value + 0.1, so rays
appear just above their source and move together in the layer tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    from ...objects import SourceItem
    from ..objects import GraphicsView  # type: ignore[misc]
    from ..raytracing import RayPath  # type: ignore[misc]

# Offset for rays above their source (keeps source icon visible)
RAY_Z_OFFSET = 0.1


class RayRenderer:
    """
    Renderer for ray paths in the graphics scene.

    Handles both hardware-accelerated OpenGL rendering and software fallback
    using QGraphicsPathItem.

    Rays are rendered per-source at source.zValue() + 0.1, so they move
    together with their source in the layer tree.
    """

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        view: GraphicsView,
    ):
        """
        Initialize the ray renderer.

        Args:
            scene: The graphics scene to render rays into
            view: The graphics view (for OpenGL overlay access)
        """
        self.scene = scene
        self.view = view

        # Track rendered ray items for software rendering
        self.ray_items: list[QtWidgets.QGraphicsPathItem] = []

        # Ray width in pixels
        self._ray_width_px: float = 2.0

        # Cache of sources for z-value lookup
        self._sources: list[SourceItem] = []

    @property
    def ray_width_px(self) -> float:
        """Get the ray width in pixels."""
        return self._ray_width_px

    @ray_width_px.setter
    def ray_width_px(self, value: float):
        """Set the ray width in pixels."""
        self._ray_width_px = float(value)

    def set_sources(self, sources: list[SourceItem]) -> None:
        """
        Set the list of sources for z-value lookup.

        Args:
            sources: List of SourceItem objects in the same order as raytracing
        """
        self._sources = list(sources)

    def clear(self) -> None:
        """Remove all ray graphics from scene."""
        # Clear OpenGL overlay if available
        if self.view.has_ray_overlay():
            self.view.clear_ray_overlay()

        # Clear software-rendered rays
        for it in self.ray_items:
            try:
                # Check if item is still in scene before removing
                if it.scene() is not None:
                    self.scene.removeItem(it)
            except RuntimeError:
                # Item was already deleted (e.g., during scene clear)
                pass
        self.ray_items.clear()

    def render(self, paths: list[RayPath]) -> None:
        """
        Render ray paths to the scene.

        Uses OpenGL hardware acceleration if available, otherwise falls back
        to software rendering with QGraphicsPathItem.

        Each source's rays are rendered at source.zValue() + 0.1.

        Args:
            paths: List of RayPath objects to render
        """
        # Try OpenGL rendering first (100x+ faster)
        if self.view.has_ray_overlay():
            # Use hardware-accelerated OpenGL rendering
            # Note: OpenGL overlay doesn't support per-source z-ordering
            # It renders all rays in a single layer above the scene
            self.view.update_ray_overlay(paths, self._ray_width_px)
            # No need to create QGraphicsPathItem objects
            self._update_path_measures(paths)
            return

        # Fallback to software rendering if OpenGL not available
        self._render_software(paths)
        self._update_path_measures(paths)

    def _get_source_z_value(self, source_index: int) -> float:
        """
        Get the z-value for rays from a given source.

        Args:
            source_index: Index of the source

        Returns:
            z-value for rays (source z-value + offset)
        """
        if 0 <= source_index < len(self._sources):
            return self._sources[source_index].zValue() + RAY_Z_OFFSET
        # Fallback if source not found
        return RAY_Z_OFFSET

    def _render_software(self, paths: list[RayPath]) -> None:
        """
        Software fallback rendering using QGraphicsPathItem.

        Each source's rays are rendered at source.zValue() + 0.1.
        Gaussian beams are drawn as filled envelope polygons with the
        central ray on top.

        Args:
            paths: List of RayPath objects to render
        """
        RAY_WIDTH_OPENGL_SCALE = 2.0

        for p in paths:
            if len(p.points) < 2:
                continue

            r, g, b, _a = p.rgba
            z_value = self._get_source_z_value(p.source_index)
            has_per_seg = len(p.intensities) >= len(p.points)

            is_gaussian = len(p.beam_radii) >= len(p.points)

            if is_gaussian:
                self._render_gaussian_beam(p, r, g, b, _a, z_value, has_per_seg)
            else:
                pen_width = self._ray_width_px * RAY_WIDTH_OPENGL_SCALE
                for i in range(len(p.points) - 1):
                    seg_path = QtGui.QPainterPath(
                        QtCore.QPointF(p.points[i][0], p.points[i][1])
                    )
                    seg_path.lineTo(p.points[i + 1][0], p.points[i + 1][1])

                    item = QtWidgets.QGraphicsPathItem(seg_path)

                    if has_per_seg:
                        seg_alpha = int(255 * max(0.0, min(1.0, p.intensities[i])))
                    else:
                        seg_alpha = _a

                    color = QtGui.QColor(r, g, b, seg_alpha)
                    pen = QtGui.QPen(color)
                    pen.setWidthF(pen_width)
                    pen.setCosmetic(True)
                    item.setPen(pen)
                    item.setZValue(z_value)

                    self.scene.addItem(item)
                    self.ray_items.append(item)

    def _render_gaussian_beam(
        self,
        p: RayPath,
        r: int,
        g: int,
        b: int,
        base_alpha: int,
        z_value: float,
        has_per_seg: bool,
    ) -> None:
        """
        Render a Gaussian beam path as nested envelope polygons.

        Draws three concentric layers (outer to inner) at different fractions
        of the 1/e^2 beam radius with increasing opacity, approximating the
        Gaussian transverse intensity profile. A thin central ray line is
        drawn on top.
        """
        points = p.points
        radii = p.beam_radii
        n = len(points)

        # Compute perpendicular direction at each point
        perps = []
        for i in range(n):
            if i < n - 1:
                seg = np.array(points[i + 1]) - np.array(points[i])
            else:
                seg = np.array(points[i]) - np.array(points[i - 1])
            seg_len = np.linalg.norm(seg)
            if seg_len > 1e-12:
                tangent = seg / seg_len
            else:
                tangent = np.array([1.0, 0.0])
            perps.append(np.array([-tangent[1], tangent[0]]))

        # Nested envelope layers: (radius_fraction, alpha_fraction)
        # Outer layer = faintest, inner = most opaque
        ENVELOPE_LAYERS = [
            (1.0, 0.10),   # 1/e^2 boundary — very faint
            (0.7, 0.18),   # ~half-power region
            (0.35, 0.30),  # core
        ]

        for radius_frac, alpha_frac in ENVELOPE_LAYERS:
            envelope_path = QtGui.QPainterPath()

            # Forward pass: upper edge (+w)
            first_upper = points[0] + radii[0] * radius_frac * perps[0]
            envelope_path.moveTo(QtCore.QPointF(float(first_upper[0]), float(first_upper[1])))
            for i in range(1, n):
                upper = points[i] + radii[i] * radius_frac * perps[i]
                envelope_path.lineTo(QtCore.QPointF(float(upper[0]), float(upper[1])))

            # Backward pass: lower edge (-w)
            for i in range(n - 1, -1, -1):
                lower = points[i] - radii[i] * radius_frac * perps[i]
                envelope_path.lineTo(QtCore.QPointF(float(lower[0]), float(lower[1])))

            envelope_path.closeSubpath()

            item = QtWidgets.QGraphicsPathItem(envelope_path)
            fill_alpha = int(255 * alpha_frac)
            item.setBrush(QtGui.QBrush(QtGui.QColor(r, g, b, fill_alpha)))
            item.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
            item.setZValue(z_value)

            self.scene.addItem(item)
            self.ray_items.append(item)

        # Central ray line on top
        RAY_WIDTH_OPENGL_SCALE = 2.0
        pen_width = self._ray_width_px * RAY_WIDTH_OPENGL_SCALE
        for i in range(n - 1):
            seg_path = QtGui.QPainterPath(
                QtCore.QPointF(float(points[i][0]), float(points[i][1]))
            )
            seg_path.lineTo(float(points[i + 1][0]), float(points[i + 1][1]))

            item = QtWidgets.QGraphicsPathItem(seg_path)

            if has_per_seg:
                seg_alpha = int(255 * max(0.0, min(1.0, p.intensities[i])))
            else:
                seg_alpha = base_alpha

            color = QtGui.QColor(r, g, b, seg_alpha)
            pen = QtGui.QPen(color)
            pen.setWidthF(pen_width)
            pen.setCosmetic(True)
            item.setPen(pen)
            item.setZValue(z_value + 0.01)

            self.scene.addItem(item)
            self.ray_items.append(item)

    def _update_path_measures(self, paths: list[RayPath]) -> None:
        """
        Update any PathMeasureItem objects after retrace.

        Args:
            paths: List of RayPath objects
        """
        from optiverse.objects.annotations.path_measure_item import PathMeasureItem

        for item in self.scene.items():
            if isinstance(item, PathMeasureItem):
                ray_index = item.get_ray_index()
                if 0 <= ray_index < len(paths):
                    item.update_path(paths[ray_index].points)
