"""Ray path rendering for the UI.

This module handles the visual rendering of traced ray paths to the scene,
using either OpenGL hardware acceleration or software fallback.

Each source's rays are rendered at the source's z-value + 0.1, so rays
appear just above their source and move together in the layer tree.
"""

from __future__ import annotations

import ctypes
import logging
import math
from typing import TYPE_CHECKING

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets, sip
from PyQt6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
)

if TYPE_CHECKING:
    from ...objects import SourceItem
    from ..objects import GraphicsView  # type: ignore[misc]
    from ..raytracing import RayPath  # type: ignore[misc]

_logger = logging.getLogger(__name__)

try:
    from OpenGL import GL

    _OPENGL_AVAILABLE = True
except ImportError:
    GL = None  # type: ignore[misc, assignment]
    _OPENGL_AVAILABLE = False

# Offset for rays above their source (keeps source icon visible)
RAY_Z_OFFSET = 0.1

# Draw envelope to this multiple of w so alpha is near zero at polygon edge.
_GAUSSIAN_DRAW_EXTENT = 2.35

# Contour layers for software fallback only (no GPU).
_GAUSSIAN_FALLBACK_CONTOURS = 48

# Fallback QImage resolution (px per scene-mm) and cap when GL unavailable.
_GAUSSIAN_FALLBACK_DPI = 4.0
_GAUSSIAN_FALLBACK_IMAGE_PX_CAP = 4096

_GAUSSIAN_VERTEX_SHADER = """
#version 120
attribute vec2 a_pos;
attribute vec2 a_axis;
attribute float a_w;
uniform mat3 u_mvp;
varying vec2 v_frag;
varying vec2 v_axis;
varying float v_w;

void main() {
    vec3 ndc = u_mvp * vec3(a_pos, 1.0);
    gl_Position = vec4(ndc.xy, 0.0, 1.0);
    v_frag = a_pos;
    v_axis = a_axis;
    v_w = a_w;
}
"""

_GAUSSIAN_FRAGMENT_SHADER = """
#version 120
varying vec2 v_frag;
varying vec2 v_axis;
varying float v_w;
uniform vec3 u_color;
uniform float u_peak;

void main() {
    float d = length(v_frag - v_axis) / max(v_w, 0.0001);
    float g = exp(-2.0 * d * d);
    float a = g * u_peak;
    gl_FragColor = vec4(u_color * a, a);
}
"""


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


def _build_gaussian_triangle_strip(
    local_pts: list[tuple[float, float]],
    ws: list[float],
    perps: list[tuple[float, float]],
    extent: float,
) -> np.ndarray:
    """Triangle strip with per-pixel distance data.

    Vertex format: [pos_x, pos_y, axis_x, axis_y, w] -- 5 floats, 20 bytes stride.
    The fragment shader computes ``length(frag - axis) / w`` per pixel.
    """
    n = len(local_pts)
    out = np.empty((2 * n, 5), dtype=np.float32)
    for i in range(n):
        xi, yi = local_pts[i]
        pxi, pyi = perps[i]
        w = float(ws[i])
        ox = extent * w * pxi
        oy = extent * w * pyi
        # Top vertex
        out[2 * i, 0] = xi + ox
        out[2 * i, 1] = yi + oy
        out[2 * i, 2] = xi
        out[2 * i, 3] = yi
        out[2 * i, 4] = w
        # Bottom vertex
        out[2 * i + 1, 0] = xi - ox
        out[2 * i + 1, 1] = yi - oy
        out[2 * i + 1, 2] = xi
        out[2 * i + 1, 3] = yi
        out[2 * i + 1, 4] = w
    return out


class _GaussianBeamItem(QtWidgets.QGraphicsItem):
    """
    Gaussian envelope: GPU triangle strip + fragment shader exp(-2*d^2), or
    software contour fallback when OpenGL / shaders are unavailable.
    """

    _gl_program: QOpenGLShaderProgram | None = None
    _gl_init_attempted: bool = False
    _gl_ok: bool = False

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

        self._strip_vertices = _build_gaussian_triangle_strip(
            local_pts, ws, perps, extent
        )
        self._vertex_count = int(self._strip_vertices.shape[0])

        self._vbo: QOpenGLBuffer | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._vbo_uploaded = False

        # Software fallback cache
        self._fallback_dpi = 0.0
        self._fallback_img: QtGui.QImage | None = None

        self.setCacheMode(QtWidgets.QGraphicsItem.CacheMode.NoCache)

    @classmethod
    def _ensure_shader(cls) -> bool:
        if cls._gl_init_attempted:
            return cls._gl_ok
        cls._gl_init_attempted = True
        if not _OPENGL_AVAILABLE:
            cls._gl_ok = False
            return False

        prog = QOpenGLShaderProgram()
        if not prog.addShaderFromSourceCode(
            QOpenGLShader.ShaderTypeBit.Vertex, _GAUSSIAN_VERTEX_SHADER
        ):
            _logger.error("Gaussian beam vertex shader: %s", prog.log())
            cls._gl_ok = False
            return False
        if not prog.addShaderFromSourceCode(
            QOpenGLShader.ShaderTypeBit.Fragment, _GAUSSIAN_FRAGMENT_SHADER
        ):
            _logger.error("Gaussian beam fragment shader: %s", prog.log())
            cls._gl_ok = False
            return False
        if not prog.link():
            _logger.error("Gaussian beam shader link: %s", prog.log())
            cls._gl_ok = False
            return False

        cls._gl_program = prog
        cls._gl_ok = True
        _logger.debug("Gaussian beam GLSL program linked OK")
        return True

    def _ensure_vbo(self) -> bool:
        if self._vbo_uploaded and self._vbo is not None and self._vao is not None:
            return True
        if not _GaussianBeamItem._ensure_shader() or _GaussianBeamItem._gl_program is None:
            return False

        prog = _GaussianBeamItem._gl_program
        raw = self._strip_vertices.tobytes()
        nbytes = len(raw)

        vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        if not vbo.create():
            return False
        vbo.bind()
        vbo.allocate(sip.voidptr(raw), nbytes)

        vao = QOpenGLVertexArrayObject()
        if not vao.create():
            vbo.release()
            return False

        vao.bind()
        vbo.bind()

        # Vertex layout: [pos_x, pos_y, axis_x, axis_y, w] = 5 floats = 20 bytes
        stride = 20
        pos_loc = prog.attributeLocation("a_pos")
        axis_loc = prog.attributeLocation("a_axis")
        w_loc = prog.attributeLocation("a_w")
        if pos_loc < 0 or axis_loc < 0 or w_loc < 0:
            _logger.error(
                "Gaussian shader missing attrs (a_pos=%s a_axis=%s a_w=%s)",
                pos_loc, axis_loc, w_loc,
            )
            vao.release()
            vbo.release()
            return False

        GL.glEnableVertexAttribArray(pos_loc)
        GL.glVertexAttribPointer(pos_loc, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, None)
        GL.glEnableVertexAttribArray(axis_loc)
        GL.glVertexAttribPointer(
            axis_loc, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(8)
        )
        GL.glEnableVertexAttribArray(w_loc)
        GL.glVertexAttribPointer(
            w_loc, 1, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(16)
        )

        vbo.release()
        vao.release()

        self._vbo = vbo
        self._vao = vao
        self._vbo_uploaded = True
        self._strip_vertices = np.empty(0, dtype=np.float32)
        return True

    def _mvp_item_to_ndc(
        self, dt: QtGui.QTransform, vw: float, vh: float
    ) -> QtGui.QMatrix3x3:
        """Item-local (mm) -> NDC: Qt device coords (Y down) then flip Y for GL NDC."""
        # QTransform: x' = m11*x + m21*y + m31, y' = m12*x + m22*y + m32
        m11, m21, m31 = dt.m11(), dt.m21(), dt.m31()
        m12, m22, m32 = dt.m12(), dt.m22(), dt.m32()
        inv_w = 2.0 / max(vw, 1.0)
        inv_h = 2.0 / max(vh, 1.0)
        # ndc_x = 2*x'/vw - 1, ndc_y = 1 - 2*y'/vh
        return QtGui.QMatrix3x3([
            m11 * inv_w,
            m21 * inv_w,
            m31 * inv_w - 1.0,
            -m12 * inv_h,
            -m22 * inv_h,
            1.0 - m32 * inv_h,
            0.0,
            0.0,
            1.0,
        ])

    def _draw_gl(self, painter: QtGui.QPainter, widget: QtWidgets.QWidget) -> bool:
        if not _OPENGL_AVAILABLE or GL is None:
            return False
        if QtGui.QOpenGLContext.currentContext() is None:
            return False
        if not self._ensure_vbo() or self._vao is None:
            return False
        prog = _GaussianBeamItem._gl_program
        if prog is None:
            return False

        vp = GL.glGetIntegerv(GL.GL_VIEWPORT)
        vw = float(vp[2])
        vh = float(vp[3])
        if vw < 1.0 or vh < 1.0:
            return False

        dt = painter.deviceTransform()
        mvp = self._mvp_item_to_ndc(dt, vw, vh)

        prev_blend = GL.glIsEnabled(GL.GL_BLEND)
        prev_depth = GL.glIsEnabled(GL.GL_DEPTH_TEST)

        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDisable(GL.GL_DEPTH_TEST)

        if not prog.bind():
            return False

        prog.setUniformValue("u_mvp", mvp)
        prog.setUniformValue(
            "u_color",
            QtGui.QVector3D(
                self._r / 255.0, self._g / 255.0, self._b / 255.0
            ),
        )
        prog.setUniformValue("u_peak", float(self._P))

        self._vao.bind()
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, self._vertex_count)
        self._vao.release()
        prog.release()

        if prev_depth:
            GL.glEnable(GL.GL_DEPTH_TEST)
        else:
            GL.glDisable(GL.GL_DEPTH_TEST)
        if not prev_blend:
            GL.glDisable(GL.GL_BLEND)

        return True

    def _render_fallback_image(self, dpi: float) -> QtGui.QImage:
        rect = self._item_rect
        bw = max(rect.width(), 1e-6)
        bh = max(rect.height(), 1e-6)
        w_px = max(
            1, min(int(math.ceil(bw * dpi)), _GAUSSIAN_FALLBACK_IMAGE_PX_CAP)
        )
        h_px = max(
            1, min(int(math.ceil(bh * dpi)), _GAUSSIAN_FALLBACK_IMAGE_PX_CAP)
        )

        img = QtGui.QImage(w_px, h_px, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)

        ip = QtGui.QPainter(img)
        ip.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        ip.scale(w_px / bw, h_px / bh)
        ip.translate(-rect.left(), -rect.top())
        ip.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Source)

        n = len(self._local_pts)
        L = _GAUSSIAN_FALLBACK_CONTOURS
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

    def _paint_fallback(self, painter: QtGui.QPainter) -> None:
        current_dpi = abs(painter.deviceTransform().m11())
        if current_dpi > 0.1:
            if (
                self._fallback_img is None
                or abs(current_dpi / max(self._fallback_dpi, 0.01) - 1.0) > 0.25
            ):
                self._fallback_dpi = current_dpi
                self._fallback_img = self._render_fallback_image(
                    max(current_dpi, _GAUSSIAN_FALLBACK_DPI)
                )
        else:
            if self._fallback_img is None:
                self._fallback_img = self._render_fallback_image(_GAUSSIAN_FALLBACK_DPI)

        painter.drawImage(
            self._item_rect,
            self._fallback_img,
            QtCore.QRectF(
                0.0,
                0.0,
                float(self._fallback_img.width()),
                float(self._fallback_img.height()),
            ),
        )

    def boundingRect(self) -> QtCore.QRectF:
        return self._item_rect

    def paint(
        self,
        painter: QtGui.QPainter | None,
        option: QtWidgets.QStyleOptionGraphicsItem | None,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        if painter is None:
            return
        if _OPENGL_AVAILABLE and widget is not None:
            painter.beginNativePainting()
            try:
                if self._draw_gl(painter, widget):
                    return
            finally:
                painter.endNativePainting()

        self._paint_fallback(painter)

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
        # Use the dedicated OpenGL line overlay for non-Gaussian rays.
        # Gaussian beams use per-item GLSL rendering via _GaussianBeamItem.
        use_gl = self.view.has_ray_overlay() and not any(
            len(p.beam_radii) >= len(p.points) for p in paths
        )
        if use_gl:
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
        """Render rays as QGraphicsItems (line segments and Gaussian envelopes).

        Gaussian beams are rendered via _GaussianBeamItem which uses GLSL
        shaders when an OpenGL context is active, otherwise falls back to
        contour-polygon rasterisation.

        Args:
            paths: List of RayPath objects
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
        Gaussian envelope: GLSL triangle strip when OpenGL viewport is active,
        else contour rasterisation fallback.

        The path is split at sharp direction changes (mirrors) so each
        straight section gets its own triangle strip — prevents degenerate
        bowtie triangles at reflection corners.
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

        # Detect sharp direction changes and split into segments.
        # The shared point at each split belongs to BOTH segments so the
        # Gaussian envelope is continuous at the interface.
        _ANGLE_THRESHOLD = 0.25  # ~14 degrees
        splits: list[int] = [0]
        for i in range(1, n - 1):
            d_prev = pts[i] - pts[i - 1]
            d_next = pts[i + 1] - pts[i]
            lp = float(np.linalg.norm(d_prev))
            ln = float(np.linalg.norm(d_next))
            if lp > 1e-12 and ln > 1e-12:
                cos_a = float(np.dot(d_prev, d_next)) / (lp * ln)
                if cos_a < math.cos(_ANGLE_THRESHOLD):
                    splits.append(i)
        splits.append(n)

        for seg_idx in range(len(splits) - 1):
            s0 = splits[seg_idx]
            s1 = splits[seg_idx + 1]
            if seg_idx < len(splits) - 2:
                s1 += 1  # include the shared corner point
            seg_n = s1 - s0
            if seg_n < 2:
                continue
            self._render_gaussian_segment(
                pts[s0:s1], ws[s0:s1], seg_n, extent, P, r, g, b, z_value,
            )

    def _render_gaussian_segment(
        self,
        pts: list[np.ndarray],
        ws: list[float],
        n: int,
        extent: float,
        P: float,
        r: int,
        g: int,
        b: int,
        z_value: float,
    ) -> None:
        """Render one straight section of a Gaussian beam as a triangle strip."""
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

        # Laplacian smoothing removes tiny oscillations that create visible
        # zigzag at the strip edges (amplified by large beam widths).
        for _pass in range(5):
            smoothed = list(perps_np)
            for j in range(1, n - 1):
                avg = 0.25 * perps_np[j - 1] + 0.5 * perps_np[j] + 0.25 * perps_np[j + 1]
                nrm = float(np.linalg.norm(avg))
                if nrm > 1e-12:
                    smoothed[j] = avg / nrm
            perps_np = smoothed

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
