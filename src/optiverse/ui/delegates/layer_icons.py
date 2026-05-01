"""QPainter-drawn vector icons for the layer panel.

Replaces emoji glyphs (which require a color-emoji font not available on all
platforms, e.g. WSL/Ubuntu) with simple geometric drawing that works everywhere.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui

_PADDING = 4


def _icon_color(
    palette: QtGui.QPalette,
    role: QtGui.QPalette.ColorRole,
) -> QtGui.QColor:
    return palette.color(role)


def _make_pen(color: QtGui.QColor, width: float = 1.4) -> QtGui.QPen:
    pen = QtGui.QPen(color, width)
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    return pen


# -- Eye (visible) -----------------------------------------------------------


def draw_eye_icon(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    palette: QtGui.QPalette,
    color_role: QtGui.QPalette.ColorRole,
) -> None:
    """Open eye: almond outline + filled iris circle (with pupil cutout)."""
    color = _icon_color(palette, color_role)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    # Outline almond shape
    painter.setPen(_make_pen(color))
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    r = QtCore.QRectF(rect).adjusted(_PADDING, _PADDING, -_PADDING, -_PADDING)
    cx = r.center().x()
    cy = r.center().y()
    hw = r.width() / 2.0
    hh = r.height() / 2.0

    # Almond/eye outline, use a slightly curved cubic for nicer look
    curve = hh * 0.65
    path = QtGui.QPainterPath()
    path.moveTo(cx - hw, cy)
    path.cubicTo(cx - hw * 0.2, cy - curve,
                 cx + hw * 0.2, cy - curve,
                 cx + hw, cy)
    path.cubicTo(cx + hw * 0.2, cy + curve,
                 cx - hw * 0.2, cy + curve,
                 cx - hw, cy)
    painter.drawPath(path)

    # Draw filled iris with cutout (pupil)
    iris_r = curve * 0.85
    cutout_r = iris_r * 0.25
    iris_path = QtGui.QPainterPath()
    iris_path.addEllipse(QtCore.QPointF(cx, cy), iris_r, iris_r)
    iris_path.addEllipse(QtCore.QPointF(cx, cy), cutout_r, cutout_r)
    iris_path.setFillRule(QtCore.Qt.FillRule.OddEvenFill)
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(iris_path)

    painter.restore()


# -- Hidden (not visible) ----------------------------------------------------


def draw_hidden_icon(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    palette: QtGui.QPalette,
    color_role: QtGui.QPalette.ColorRole,
) -> None:
    """Open circle – matches the old "○" glyph."""
    color = _icon_color(palette, color_role)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setPen(_make_pen(color))
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

    r = QtCore.QRectF(rect).adjusted(_PADDING, _PADDING, -_PADDING, -_PADDING)
    radius = min(r.width(), r.height()) / 2.0 - 0.5
    painter.drawEllipse(r.center(), radius, radius)

    painter.restore()


# -- Locked -------------------------------------------------------------------


def draw_lock_icon(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    palette: QtGui.QPalette,
    color_role: QtGui.QPalette.ColorRole,
) -> None:
    """Closed padlock: both shackle legs connect to body."""
    color = _icon_color(palette, color_role)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    r = QtCore.QRectF(rect).adjusted(_PADDING, _PADDING, -_PADDING, -_PADDING)
    cx = r.center().x()
    w = r.width()
    h = r.height()

    body_h = h * 0.50
    body_w = w * 0.72
    body_top = r.bottom() - body_h
    body_rect = QtCore.QRectF(cx - body_w / 2, body_top, body_w, body_h)

    shackle_w = body_w * 0.60
    arc_rect = QtCore.QRectF(cx - shackle_w / 2, r.top(), shackle_w, shackle_w)
    arc_bottom_y = r.top() + shackle_w / 2

    pen = _make_pen(color)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

    # Left leg
    painter.drawLine(
        QtCore.QPointF(cx - shackle_w / 2, body_top),
        QtCore.QPointF(cx - shackle_w / 2, arc_bottom_y),
    )
    # Arc across the top
    painter.drawArc(arc_rect, 0, 180 * 16)
    # Right leg
    painter.drawLine(
        QtCore.QPointF(cx + shackle_w / 2, arc_bottom_y),
        QtCore.QPointF(cx + shackle_w / 2, body_top),
    )

    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(body_rect, 1.0, 1.0)

    painter.restore()


# -- Unlocked -----------------------------------------------------------------


def draw_unlock_icon(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    palette: QtGui.QPalette,
    color_role: QtGui.QPalette.ColorRole,
) -> None:
    """Open padlock: left leg of shackle connects to body, right leg is raised."""
    color = _icon_color(palette, color_role)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    r = QtCore.QRectF(rect).adjusted(_PADDING, _PADDING, -_PADDING, -_PADDING)
    cx = r.center().x()
    w = r.width()
    h = r.height()

    body_h = h * 0.50
    body_w = w * 0.72
    body_top = r.bottom() - body_h
    body_rect = QtCore.QRectF(cx - body_w / 2, body_top, body_w, body_h)

    # Shackle: same arc as locked, but shift the whole shackle up so
    # the right leg lifts off the body while the left leg stays connected.
    shackle_w = body_w * 0.60
    arc_rect = QtCore.QRectF(cx - shackle_w / 2, r.top(), shackle_w, shackle_w)
    arc_bottom = r.top() + shackle_w

    pen = _make_pen(color)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

    # Left leg: from body top up to where the arc starts
    painter.drawLine(
        QtCore.QPointF(cx - shackle_w / 2, body_top),
        QtCore.QPointF(cx - shackle_w / 2, arc_bottom / 2 + r.top() / 2),
    )
    # Arc across the top
    painter.drawArc(arc_rect, 0, 180 * 16)
    # Right leg: short stub hanging from arc (doesn't reach the body)
    painter.drawLine(
        QtCore.QPointF(cx + shackle_w / 2, arc_bottom / 2 + r.top() / 2),
        QtCore.QPointF(cx + shackle_w / 2, body_top - h * 0.15),
    )

    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(body_rect, 1.0, 1.0)

    painter.restore()


# -- Folder -------------------------------------------------------------------


def draw_folder_icon(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    palette: QtGui.QPalette,
    color_role: QtGui.QPalette.ColorRole,
) -> None:
    """Folder with stepped tab -- clear at small sizes."""
    color = _icon_color(palette, color_role)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    r = QtCore.QRectF(rect).adjusted(_PADDING, _PADDING, -_PADDING, -_PADDING)
    x, y, w, h = r.x(), r.y(), r.width(), r.height()

    tab_w = w * 0.40
    tab_h = h * 0.20
    body_top = y + tab_h

    path = QtGui.QPainterPath()
    path.moveTo(x, y + h)
    path.lineTo(x, y)
    path.lineTo(x + tab_w, y)
    path.lineTo(x + tab_w, body_top)
    path.lineTo(x + w, body_top)
    path.lineTo(x + w, y + h)
    path.closeSubpath()

    painter.setPen(_make_pen(color))
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    painter.drawPath(path)

    painter.restore()


# -- Link (chain) -------------------------------------------------------------


def draw_link_icon(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    palette: QtGui.QPalette,
    color_role: QtGui.QPalette.ColorRole,
) -> None:
    """Two interlocking oval chain links."""
    color = _icon_color(palette, color_role)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setPen(_make_pen(color, 1.3))
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

    r = QtCore.QRectF(rect).adjusted(_PADDING, _PADDING, -_PADDING, -_PADDING)
    cx = r.center().x()
    cy = r.center().y()
    link_w = r.width() * 0.42
    link_h = r.height() * 0.55
    offset = link_w * 0.35

    left = QtCore.QRectF(cx - offset - link_w / 2, cy - link_h / 2, link_w, link_h)
    right = QtCore.QRectF(cx + offset - link_w / 2, cy - link_h / 2, link_w, link_h)

    painter.drawRoundedRect(left, link_h / 2, link_h / 2)
    painter.drawRoundedRect(right, link_h / 2, link_h / 2)

    painter.restore()


# -- Toolbar helpers (QIcon from painting) ------------------------------------


def _paint_to_pixmap(
    size: int,
    draw_fn: object,
    palette: QtGui.QPalette,
    color_role: QtGui.QPalette.ColorRole,
) -> QtGui.QPixmap:
    """Render a draw function into a QPixmap for use in QIcon."""
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    rect = QtCore.QRect(0, 0, size, size)
    draw_fn(painter, rect, palette, color_role)  # type: ignore[operator]
    painter.end()
    return pixmap


def make_folder_add_icon(
    size: int,
    palette: QtGui.QPalette,
    color_role: QtGui.QPalette.ColorRole,
) -> QtGui.QIcon:
    """Folder icon with a '+' badge to the right."""
    pw = int(size * 1.5)
    pixmap = QtGui.QPixmap(pw, size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    # Draw folder in the left portion, leaving room for badge
    folder_size = int(size * 0.85)
    folder_rect = QtCore.QRect(0, size - folder_size, folder_size, folder_size)
    draw_folder_icon(painter, folder_rect, palette, color_role)

    color = _icon_color(palette, color_role)
    painter.setPen(_make_pen(color, 1.6))
    bx = folder_size + (pw - folder_size) / 2.0
    by = size * 0.5
    arm = size * 0.2
    painter.drawLine(QtCore.QPointF(bx, by - arm), QtCore.QPointF(bx, by + arm))
    painter.drawLine(QtCore.QPointF(bx - arm, by), QtCore.QPointF(bx + arm, by))

    painter.end()
    return QtGui.QIcon(pixmap)


def make_folder_remove_icon(
    size: int,
    palette: QtGui.QPalette,
    color_role: QtGui.QPalette.ColorRole,
) -> QtGui.QIcon:
    """Folder icon with a '−' badge to the right."""
    pw = int(size * 1.5)
    pixmap = QtGui.QPixmap(pw, size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    # Draw folder in the left portion, leaving room for badge
    folder_size = int(size * 0.85)
    folder_rect = QtCore.QRect(0, size - folder_size, folder_size, folder_size)
    draw_folder_icon(painter, folder_rect, palette, color_role)

    color = _icon_color(palette, color_role)
    painter.setPen(_make_pen(color, 1.6))
    bx = folder_size + (pw - folder_size) / 2.0
    by = size * 0.5
    arm = size * 0.2
    painter.drawLine(QtCore.QPointF(bx - arm, by), QtCore.QPointF(bx + arm, by))

    painter.end()
    return QtGui.QIcon(pixmap)
