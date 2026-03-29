"""Ray path rendering for the UI.

This module handles the visual rendering of traced ray paths to the scene,
using either OpenGL hardware acceleration or software fallback.

Each source's rays are rendered at the source's z-value + 0.1, so rays
appear just above their source and move together in the layer tree.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    from ...objects import SourceItem
    from ..objects import GraphicsView  # type: ignore[misc]
    from ..raytracing import RayPath  # type: ignore[misc]

# Offset for rays above their source (keeps source icon visible)
RAY_Z_OFFSET = 0.1

# Draw envelope to this multiple of w so alpha is near zero at polygon edge.
_GAUSSIAN_DRAW_EXTENT = 2.35

# Contour layers for transverse Gaussian profile.
_GAUSSIAN_N_CONTOURS = 48

# Pre-render resolution: pixels per scene-mm.
_GAUSSIAN_RENDER_DPI = 4.0

# Hard cap so huge beams don't allocate enormous bitmaps.
_GAUSSIAN_IMAGE_PX_CAP = 4096


def _gaussian_beam_polygon(
    local_pts: list[tuple[float, float]],
    ws: list[float],
    perps: list[tuple[float, float]],
    frac: float,
    n: int,
) -> QtGui.QPolygonF:
    """Closed contour at ±frac*w from axis (item-local mm)."""
    poly = QtGui.QPolygonF()
    for i in range(n):
        xi, yi = local_pts[i]
        pxi, pyi = perps[i]
        poly.append(QtCore.QPointF(xi + frac * ws[i] * pxi, yi + frac * ws[i] * pyi))
    for i in range(n - 1, -1, -1):
        xi, yi = local_pts[i]
        pxi, pyi = perps[i]
        poly.append(QtCore.QPointF(xi - frac * ws[i] * pxi, yi - frac * ws[i] * pyi))
    return poly


class _GaussianBeamItem(QtWidgets.QGraphicsItem):
    """
    Gaussian envelope rendered to a cached QImage.

    The bitmap is rasterised at the current device resolution and re-rendered
    when the zoom changes significantly (>1.5x or <0.5x ratio).  Overlapping
    beams use Screen compositing so they brighten without clamping.
    """

    # Re-render when zoom ratio exceeds these bounds.
    _ZOOM_UPPER = 1.5
    _ZOOM_LOWER = 0.5

    def __init__(
        self,
        item_rect: QtCore.QRectF,
        local_pts: list[tuple[float, float]],
        ws: list[float],
        perps: list[tuple[float, float]],
        extent: float,
        r: int,
        g: int,
        b: int,
        peak_alpha: float,
        parent: QtWidgets.QGraphicsItem | None = None,
    ) -> None:
        super().__init__(parent)
        self._item_rect = item_rect
        self._local_pts = local_pts
        self._ws = ws
        self._perps = perps
        self._extent = extent
        self._r, self._g, self._b = r, g, b
        self._P = peak_alpha

        self._cached_dpi = _GAUSSIAN_RENDER_DPI
        self._cached_img = self._render_to_image(self._cached_dpi)
        self.setCacheMode(QtWidgets.QGraphicsItem.CacheMode.NoCache)

    def _render_to_image(self, dpi: float) -> QtGui.QImage:
        rect = self._item_rect
        bw = max(rect.width(), 1e-6)
        bh = max(rect.height(), 1e-6)
        w_px = max(1, min(int(math.ceil(bw * dpi)), _GAUSSIAN_IMAGE_PX_CAP))
        h_px = max(1, min(int(math.ceil(bh * dpi)), _GAUSSIAN_IMAGE_PX_CAP))

        img = QtGui.QImage(w_px, h_px, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)

        ip = QtGui.QPainter(img)
        ip.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        ip.scale(w_px / bw, h_px / bh)
        ip.translate(-rect.left(), -rect.top())
        ip.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Source)

        n = len(self._local_pts)
        L = _GAUSSIAN_N_CONTOURS
        extent = self._extent
        r, g, b, P = self._r, self._g, self._b, self._P

        for k in range(L):
            frac = extent * (L - k) / L
            a = max(0, min(255, int(round(255.0 * math.exp(-2.0 * frac * frac) * P))))
            if a < 1:
                continue
            poly = _gaussian_beam_polygon(self._local_pts, self._ws, self._perps, frac, n)
            ip.setPen(QtCore.Qt.PenStyle.NoPen)
            ip.setBrush(QtGui.QColor(r, g, b, a))
            ip.drawPolygon(poly)

        ip.end()
        return img

    def boundingRect(self) -> QtCore.QRectF:
        return self._item_rect

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        # Adapt resolution to current zoom level
        current_dpi = abs(painter.deviceTransform().m11())
        if current_dpi > 0.1:
            ratio = current_dpi / max(self._cached_dpi, 0.01)
            if ratio > self._ZOOM_UPPER or ratio < self._ZOOM_LOWER:
                self._cached_dpi = current_dpi
                self._cached_img = self._render_to_image(current_dpi)

        prev_mode = painter.compositionMode()
        painter.setCompositionMode(
            QtGui.QPainter.CompositionMode.CompositionMode_Screen
        )
        painter.drawImage(
            self._item_rect,
            self._cached_img,
            QtCore.QRectF(
                0.0, 0.0,
                float(self._cached_img.width()),
                float(self._cached_img.height()),
            ),
        )
        painter.setCompositionMode(prev_mode)

    def shape(self) -> QtGui.QPainterPath:
        path = QtGui.QPainterPath()
        path.addRect(self._item_rect)
        return path


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

        # Track rendered ray items for software rendering (paths + Gaussian items)
        self.ray_items: list[QtWidgets.QGraphicsItem] = []

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
        # Try OpenGL rendering first (100x+ faster). Gaussian envelopes need software paths.
        use_gl = self.view.has_ray_overlay() and not any(
            len(p.beam_radii) >= len(p.points) for p in paths
        )
        if use_gl:
            # Note: OpenGL overlay doesn't support per-source z-ordering
            self.view.update_ray_overlay(paths, self._ray_width_px)
            self._update_path_measures(paths)
            return

        if self.view.has_ray_overlay():
            self.view.clear_ray_overlay()

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
        Render a Gaussian beam as one cached item: 128 contours rasterised
        offscreen with CompositionMode_Source (exact alpha per ring, no Y banding).
        """
        points = p.points
        radii = p.beam_radii
        n = len(points)
        if n < 2:
            return

        extent = _GAUSSIAN_DRAW_EXTENT
        peak_alpha = 0.85

        if has_per_seg and len(p.intensities) > 0:
            cnt = min(len(p.intensities), n)
            avg_intensity = sum(
                max(0.0, min(1.0, p.intensities[j])) for j in range(cnt)
            ) / cnt
        else:
            avg_intensity = base_alpha / 255.0

        P = peak_alpha * avg_intensity

        pts = [np.asarray(points[i], dtype=float) for i in range(n)]
        ws = [float(radii[i]) for i in range(n)]

        perps_np: list[np.ndarray] = []
        for i in range(n):
            if i == 0:
                seg = pts[1] - pts[0]
            elif i == n - 1:
                seg = pts[-1] - pts[-2]
            else:
                seg = pts[i + 1] - pts[i - 1]
            slen = float(np.linalg.norm(seg))
            if slen < 1e-12:
                perps_np.append(np.array([0.0, 1.0]))
            else:
                t = seg / slen
                perps_np.append(np.array([-t[1], t[0]]))

        min_x = min_y = math.inf
        max_x = max_y = -math.inf
        pad = 2.0
        for i in range(n):
            x, y = float(pts[i][0]), float(pts[i][1])
            px, py = float(perps_np[i][0]), float(perps_np[i][1])
            half = extent * ws[i]
            for sgn in (-1.0, 1.0):
                xx = x + sgn * half * px
                yy = y + sgn * half * py
                min_x = min(min_x, xx)
                min_y = min(min_y, yy)
                max_x = max(max_x, xx)
                max_y = max(max_y, yy)

        min_x -= pad
        min_y -= pad
        max_x += pad
        max_y += pad
        bw = max(max_x - min_x, 1e-6)
        bh = max(max_y - min_y, 1e-6)

        local_pts = [
            (float(pts[i][0] - min_x), float(pts[i][1] - min_y)) for i in range(n)
        ]
        perps_t = [(float(perps_np[i][0]), float(perps_np[i][1])) for i in range(n)]

        item = _GaussianBeamItem(
            QtCore.QRectF(0.0, 0.0, bw, bh),
            local_pts,
            ws,
            perps_t,
            extent,
            r,
            g,
            b,
            P,
        )
        item.setPos(QtCore.QPointF(min_x, min_y))
        item.setZValue(z_value)
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
