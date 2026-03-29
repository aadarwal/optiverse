from __future__ import annotations

import math
import uuid
from typing import TYPE_CHECKING, Any

from PyQt6 import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    from ...objects.rotation_handler import WheelRotationTracker

from ...core.protocols import HasLayerState
from ...ui.widgets.smart_spinbox import SmartDoubleSpinBox


class RectangleItem(QtWidgets.QGraphicsObject):
    """
    Simple annotation rectangle (no optical effect).
    Single-click placement with default size; movable and selectable.
    Supports Ctrl+drag and Ctrl+wheel for rotation.
    """

    # Type name for layer panel identification
    type_name: str = "rectangle"

    def __init__(
        self, width_mm: float = 60.0, height_mm: float = 40.0, item_uuid: str | None = None
    ):
        super().__init__()
        self.item_uuid = item_uuid if item_uuid else str(uuid.uuid4())
        # Custom display name for layer panel (None = use type_name)
        self.display_name: str | None = None
        self._w = float(width_mm)
        self._h = float(height_mm)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.setAcceptHoverEvents(True)
        self._hovered = False
        self.setZValue(100.0)
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self.setTransformOriginPoint(0.0, 0.0)

        # Rotation mode state (Ctrl + drag to rotate)
        self._rotating = False
        self._rotation_start_angle = 0.0
        self._rotation_initial = 0.0
        self._wheel_tracker: WheelRotationTracker | None = None

    def boundingRect(self) -> QtCore.QRectF:
        w = max(1.0, self._w)
        h = max(1.0, self._h)
        return QtCore.QRectF(-w / 2.0, -h / 2.0, w, h)

    def shape(self) -> QtGui.QPainterPath:
        path = QtGui.QPainterPath()
        path.addRect(self.boundingRect())
        return path

    def paint(self, p: QtGui.QPainter | None, opt, widget=None):
        if p is None:
            return
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = self.boundingRect()
        # Fill 20% gray
        p.setBrush(QtGui.QBrush(QtGui.QColor(200, 200, 200, 120)))
        # Black stroke
        pen = QtGui.QPen(QtGui.QColor(10, 10, 10), 2.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawRect(rect)

        # Add blue tint if selected (matching ComponentSprite selection feedback)
        if self.isSelected():
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(30, 144, 255, 70))  # Translucent blue
            p.drawRect(rect)
        elif self._hovered:
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(30, 144, 255, 35))  # Lighter hover tint
            p.drawRect(rect)

    def hoverEnterEvent(self, ev: QtWidgets.QGraphicsSceneHoverEvent | None) -> None:
        if ev is None:
            return
        self._hovered = True
        self.update()
        scene = self.scene()
        if scene is not None:
            views = scene.views()
            if views:
                vp = views[0].viewport()
                if vp is not None:
                    vp.update()
        super().hoverEnterEvent(ev)

    def hoverLeaveEvent(self, ev: QtWidgets.QGraphicsSceneHoverEvent | None) -> None:
        if ev is None:
            return
        self._hovered = False
        self.update()
        scene = self.scene()
        if scene is not None:
            views = scene.views()
            if views:
                vp = views[0].viewport()
                if vp is not None:
                    vp.update()
        super().hoverLeaveEvent(ev)

    def contextMenuEvent(self, ev: QtWidgets.QGraphicsSceneContextMenuEvent | None):
        if ev is None:
            return
        m = QtWidgets.QMenu()
        act_edit = m.addAction("Edit")
        act_del = m.addAction("Delete")

        # Add z-order options
        m.addSeparator()
        act_bring_to_front = m.addAction("Bring to Front")
        act_bring_forward = m.addAction("Bring Forward")
        act_send_backward = m.addAction("Send Backward")
        act_send_to_back = m.addAction("Send to Back")

        a = m.exec(ev.screenPos())
        if a == act_edit:
            self.open_editor()
        elif a == act_del:
            scene = self.scene()
            if scene is not None:
                from ...core.undo_commands import RemoveItemCommand

                layer_state = None
                undo_stack = None
                if scene.views():
                    mw = scene.views()[0].window()
                    if isinstance(mw, HasLayerState):
                        layer_state = mw.layer_state
                    undo_stack = getattr(mw, "undo_stack", None)
                cmd = RemoveItemCommand(scene, self, layer_state)
                if undo_stack:
                    undo_stack.push(cmd)
                else:
                    cmd.execute()
        else:
            # Handle z-order actions
            action_map = {
                act_bring_to_front: "bring_to_front",
                act_bring_forward: "bring_forward",
                act_send_backward: "send_backward",
                act_send_to_back: "send_to_back",
            }
            if op := action_map.get(a):
                scene = self.scene()
                if scene and scene.views():
                    main_window = scene.views()[0].window()
                    if isinstance(main_window, HasLayerState) and main_window.layer_state:
                        items = list(scene.selectedItems()) if self.isSelected() else [self]
                        uuids = [it.item_uuid for it in items if hasattr(it, "item_uuid")]
                        if uuids:
                            from ...core.undo_commands import ZOrderCommand

                            cmd = ZOrderCommand(main_window.layer_state, uuids, op)
                            undo_stack = getattr(main_window, "undo_stack", None)
                            if undo_stack:
                                undo_stack.push(cmd)
                            else:
                                cmd.execute()

    def mousePressEvent(self, ev: QtWidgets.QGraphicsSceneMouseEvent | None):
        """Handle mouse press for rotation mode (Ctrl+drag) or normal drag."""
        if ev is None:
            return
        if self.isSelected() and (ev.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier):
            # Enter rotation mode
            self._rotating = True
            self._rotation_initial = self.rotation()

            # Calculate rotation center (item center in scene coordinates)
            center = self.mapToScene(self.transformOriginPoint())

            # Calculate initial angle from rotation center to mouse position
            mouse_pos = ev.scenePos()
            dx = mouse_pos.x() - center.x()
            dy = mouse_pos.y() - center.y()
            self._rotation_start_angle = math.degrees(math.atan2(dy, dx))

            # Change cursor to indicate rotation mode
            self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            ev.accept()
        else:
            # Normal drag behavior
            super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QtWidgets.QGraphicsSceneMouseEvent | None):
        """Handle mouse move for rotation or normal drag."""
        if ev is None:
            return
        if self._rotating:
            # Get rotation center (item center in scene coordinates)
            center = self.mapToScene(self.transformOriginPoint())

            # Calculate current angle from rotation center to mouse position
            mouse_pos = ev.scenePos()
            dx = mouse_pos.x() - center.x()
            dy = mouse_pos.y() - center.y()
            current_angle = math.degrees(math.atan2(dy, dx))

            # Calculate rotation delta
            angle_delta = current_angle - self._rotation_start_angle

            # Apply rotation
            new_rotation = self._rotation_initial + angle_delta

            # Shift+Ctrl: snap to absolute 45-degree increments (0, 45, 90, 135, 180, etc.)
            if ev.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier:
                new_rotation = round(new_rotation / 45.0) * 45.0

            self.setRotation(new_rotation)

            ev.accept()
        else:
            # Normal drag behavior
            super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QtWidgets.QGraphicsSceneMouseEvent | None):
        """Handle mouse release to exit rotation mode."""
        if ev is None:
            return
        if self._rotating:
            self._rotating = False
            self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
            ev.accept()
        else:
            super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev: QtWidgets.QGraphicsSceneWheelEvent | None):
        """Ctrl + wheel → rotate element (with undo tracking via WheelRotationTracker)."""
        if ev is None:
            return
        if self.isSelected() and (ev.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier):
            from ...objects.rotation_handler import WheelRotationTracker

            if self._wheel_tracker is None:
                scene = self.scene()
                undo_stack = None
                if scene is not None and scene.views():
                    mw = scene.views()[0].window()
                    undo_stack = getattr(mw, "undo_stack", None)
                if undo_stack is not None:
                    self._wheel_tracker = WheelRotationTracker(lambda: undo_stack)

            dy = ev.angleDelta().y()  # type: ignore[attr-defined]
            steps = dy / 120.0
            rotation_delta = 2.0 * steps

            if self._wheel_tracker is not None:
                self._wheel_tracker.track([self])
            self.setRotation(self.rotation() + rotation_delta)

            ev.accept()
        else:
            super().wheelEvent(ev)

    def clone(self, offset_mm: tuple[float, float] = (20.0, 20.0)) -> RectangleItem:
        """Create a deep copy of this rectangle with optional position offset."""
        from PyQt6.QtCore import QPointF

        # Create new rectangle with same dimensions
        new_item = RectangleItem(self._w, self._h)

        # Copy properties
        new_item.setRotation(self.rotation())
        new_item.setZValue(self.zValue())

        # Set offset position
        new_pos = self.scenePos() + QPointF(offset_mm[0], offset_mm[1])
        new_item.setPos(new_pos)

        return new_item

    def to_dict(self) -> dict[str, Any]:
        r = self.boundingRect()
        return {
            "type": "rectangle",
            "x": float(self.scenePos().x()),
            "y": float(self.scenePos().y()),
            "width_mm": float(r.width()),
            "height_mm": float(r.height()),
            "angle_deg": float(self.rotation()),
            "item_uuid": self.item_uuid,
            "z_value": float(self.zValue()),
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> RectangleItem:
        item_uuid = d.get("item_uuid")
        width_mm = float(d.get("width_mm", 60.0))
        height_mm = float(d.get("height_mm", 40.0))
        item = RectangleItem(width_mm, height_mm, item_uuid)
        item.setPos(float(d.get("x", 0.0)), float(d.get("y", 0.0)))
        ang = float(d.get("angle_deg", 0.0))
        item.setRotation(ang)

        # Restore z-value if present
        if "z_value" in d:
            item.setZValue(float(d["z_value"]))

        return item

    def capture_state(self) -> dict[str, Any]:
        """Capture current state for undo/redo."""
        return {
            "x": float(self.pos().x()),
            "y": float(self.pos().y()),
            "rotation": float(self.rotation()),
            "width": float(self._w),
            "height": float(self._h),
        }

    def apply_state(self, state: dict[str, Any]) -> None:
        """Restore state from undo/redo."""
        self.setPos(state["x"], state["y"])
        self.setRotation(state["rotation"])
        self.prepareGeometryChange()
        self._w = state["width"]
        self._h = state["height"]
        self.update()

    def open_editor(self):
        scene = self.scene()
        parent_window = scene.views()[0].window() if scene and scene.views() else None
        d = QtWidgets.QDialog(parent_window)
        d.setWindowTitle("Edit Rectangle")
        f = QtWidgets.QFormLayout(d)

        initial_state = self.capture_state()

        # Save initial state for rollback on cancel
        initial_x = self.pos().x()
        initial_y = self.pos().y()
        # Normalize angle to 0-360 range (same as sync_from_item())
        initial_ang = self.rotation() % 360
        if initial_ang < 0:
            initial_ang += 360
        initial_w = self._w
        initial_h = self._h

        x = SmartDoubleSpinBox()
        x.setRange(-1e6, 1e6)
        x.setDecimals(3)
        x.setSuffix(" mm")
        x.setValue(initial_x)

        y = SmartDoubleSpinBox()
        y.setRange(-1e6, 1e6)
        y.setDecimals(3)
        y.setSuffix(" mm")
        y.setValue(initial_y)

        ang = SmartDoubleSpinBox()
        ang.setRange(-1e6, 1e6)
        ang.setDecimals(2)
        ang.setSuffix(" °")
        ang.setValue(initial_ang)

        w = SmartDoubleSpinBox()
        w.setRange(1.0, 1e7)
        w.setDecimals(2)
        w.setSuffix(" mm")
        w.setValue(initial_w)

        h = SmartDoubleSpinBox()
        h.setRange(1.0, 1e7)
        h.setDecimals(2)
        h.setSuffix(" mm")
        h.setValue(initial_h)

        def update_position():
            self.setPos(x.value(), y.value())

        def update_angle():
            self.setRotation(ang.value())

        def update_size():
            self.prepareGeometryChange()
            self._w = w.value()
            self._h = h.value()
            self.update()

        x.valueChanged.connect(update_position)
        y.valueChanged.connect(update_position)
        ang.valueChanged.connect(update_angle)
        w.valueChanged.connect(update_size)
        h.valueChanged.connect(update_size)

        f.addRow("X Position", x)
        f.addRow("Y Position", y)
        f.addRow("Rotation", ang)
        f.addRow("Width", w)
        f.addRow("Height", h)

        btn = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        f.addRow(btn)
        btn.accepted.connect(d.accept)
        btn.rejected.connect(d.reject)

        result = d.exec()
        if result:
            final_state = self.capture_state()
            if initial_state != final_state:
                from ...core.undo_commands import RectangleChangeCommand

                cmd = RectangleChangeCommand(self, initial_state, final_state)
                scene = self.scene()
                if scene and scene.views():
                    mw = scene.views()[0].window()
                    undo_stack = getattr(mw, "undo_stack", None)
                    if undo_stack:
                        undo_stack.push(cmd)
        else:
            self.apply_state(initial_state)
