"""
Handler for item drag, move, and rotation tracking.

Extracts position/rotation tracking and undo command creation from MainWindow.
Supports group movement where all items in a group move together.

Architecture:
- Works WITH Qt's native selection/drag system, not against it
- Disables ItemIsMovable on secondary items during multi-selection drag
- Primary item moves normally with magnetic snap
- Secondary items are positioned explicitly via update_group_positions()
- No class-level global state - all state is instance-scoped
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from PyQt6 import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    from ...core.layer_tree_state import LayerTreeState
    from ...core.undo_stack import UndoStack


@dataclass
class DragContext:
    """
    Clean state container for an active drag operation.

    Encapsulates all drag-related state in a single dataclass,
    making it easy to initialize and clean up.
    """

    # The item being directly dragged by the mouse
    primary_item: QtWidgets.QGraphicsItem | None = None

    # Initial positions of all dragged items (for undo)
    initial_positions: dict[QtWidgets.QGraphicsItem, QtCore.QPointF] = field(
        default_factory=dict
    )

    # Initial rotations (for rotation mode)
    initial_rotations: dict[QtWidgets.QGraphicsItem, float] = field(
        default_factory=dict
    )

    # Secondary items (all items except primary)
    secondary_items: list[QtWidgets.QGraphicsItem] = field(default_factory=list)

    # Offsets of secondary items relative to primary (for coordinated movement)
    secondary_offsets: dict[QtWidgets.QGraphicsItem, QtCore.QPointF] = field(
        default_factory=dict
    )

    # Items that had ItemIsMovable disabled (to restore later)
    items_with_movable_disabled: set[QtWidgets.QGraphicsItem] = field(
        default_factory=set
    )

    # Whether this is a group drag (LayerTreeState group)
    is_group_drag: bool = False

    # Whether this is a multi-selection drag
    is_multi_selection: bool = False

    # Whether this is a group rotation (multiple items rotating together)
    is_group_rotation: bool = False

    def clear(self) -> None:
        """Reset all drag state."""
        self.primary_item = None
        self.initial_positions.clear()
        self.initial_rotations.clear()
        self.secondary_items.clear()
        self.secondary_offsets.clear()
        self.items_with_movable_disabled.clear()
        self.is_group_drag = False
        self.is_multi_selection = False
        self.is_group_rotation = False


class ItemDragHandler:
    """
    Handles item dragging, position tracking, and rotation for undo/redo support.

    This class tracks item positions on mouse press and creates appropriate
    undo commands on mouse release.

    Key design principles:
    - No class-level/global state
    - Works with Qt's selection model, not against it
    - Secondary items have ItemIsMovable disabled during drag
    - Clear separation between drag tracking and item behavior
    """

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        view: QtWidgets.QGraphicsView,
        undo_stack: UndoStack,
        snap_to_grid_getter: Callable[[], bool],
        schedule_retrace: Callable[[], None],
        layer_state: LayerTreeState | None = None,
    ):
        """
        Initialize the drag handler.

        Args:
            scene: Graphics scene containing items
            view: Graphics view for snap guide clearing
            undo_stack: Undo stack for command creation
            snap_to_grid_getter: Callable returning whether snap to grid is enabled
            schedule_retrace: Callable to schedule ray retracing
            layer_state: Optional layer state for group movement
        """
        self.scene = scene
        self.view = view
        self.undo_stack = undo_stack
        self._get_snap_to_grid = snap_to_grid_getter
        self._schedule_retrace = schedule_retrace
        self._layer_state = layer_state

        # All drag state encapsulated in DragContext
        self._drag = DragContext()

    def set_layer_state(self, layer_state: LayerTreeState) -> None:
        """Set the layer state for group movement support."""
        self._layer_state = layer_state

    def handle_mouse_press(self, event: QtGui.QMouseEvent):
        """
        Track item positions and rotations on mouse press.

        Legacy method - prefer handle_mouse_press_at_scene_pos for correct coordinates.
        """
        # Map view coordinates to scene coordinates
        if hasattr(self.view, "mapToScene"):
            scene_pos = self.view.mapToScene(event.pos())
        else:
            scene_pos = QtCore.QPointF(event.pos())
        self.handle_mouse_press_at_scene_pos(scene_pos, event.modifiers())

    def handle_mouse_press_at_scene_pos(
        self, scene_pos: QtCore.QPointF, modifiers: QtCore.Qt.KeyboardModifier
    ):
        """
        Track item positions and rotations on mouse press.

        Also handles group movement - when one grouped item is pressed,
        all group members are tracked for coordinated movement.

        Args:
            scene_pos: Mouse position in scene coordinates
            modifiers: Keyboard modifiers active during press
        """
        from ...objects import BaseObj, RectangleItem
        from ...objects.annotations import RulerItem, TextNoteItem

        # Clear previous drag state
        self._restore_secondary_movable_flags()
        self._drag.clear()

        # Check if this is a rotation operation (Ctrl modifier)
        is_rotation_mode = bool(modifiers & QtCore.Qt.KeyboardModifier.ControlModifier)

        # Get currently selected items
        selected_items = [
            it
            for it in self.scene.selectedItems()
            if isinstance(it, (BaseObj, RulerItem, TextNoteItem, RectangleItem))
        ]

        # Find the item under the mouse cursor (the one being directly dragged)
        clicked_item = self.scene.itemAt(scene_pos, QtGui.QTransform())

        # Walk up parent hierarchy to find the actual draggable item
        while clicked_item is not None:
            if isinstance(clicked_item, (BaseObj, RulerItem, TextNoteItem, RectangleItem)):
                # If clicking on a NEW item without Shift modifier,
                # don't include previously selected items in the drag.
                # This matches Qt's standard selection behavior.
                if clicked_item not in selected_items:
                    if not (modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier):
                        # Clear previous selection - only drag the new item
                        selected_items = []
                    selected_items.append(clicked_item)
                self._drag.primary_item = clicked_item
                break
            clicked_item = clicked_item.parentItem()

        if not self._drag.primary_item:
            # No draggable item found
            return

        # Check for group membership and expand selection
        if self._layer_state and hasattr(self._drag.primary_item, "item_uuid"):
            group_uuid = self._layer_state.get_group_for_item(self._drag.primary_item.item_uuid)
            if group_uuid:
                uuids = set(self._layer_state.get_group_items_recursive(group_uuid))
                if len(uuids) > 1:
                    self._drag.is_group_drag = True
                    for it in self.scene.items():
                        if hasattr(it, "item_uuid") and it.item_uuid in uuids:
                            if isinstance(
                                it, (BaseObj, RulerItem, TextNoteItem, RectangleItem)
                            ) and it not in selected_items:
                                selected_items.append(it)

        # Identify secondary items and calculate offsets
        primary_pos = self._drag.primary_item.pos()
        for item in selected_items:
            if item != self._drag.primary_item:
                self._drag.secondary_items.append(item)
                offset = item.pos() - primary_pos
                self._drag.secondary_offsets[item] = offset

        # If we have secondary items, set up multi-selection drag
        if self._drag.secondary_items:
            self._drag.is_multi_selection = True
            # Disable ItemIsMovable on secondary items so Qt doesn't try to move them
            # We'll move them explicitly in update_group_positions()
            self._disable_secondary_movable_flags()

        # Store initial positions for all items (for undo)
        for it in selected_items:
            self._drag.initial_positions[it] = QtCore.QPointF(it.pos())

            # Track rotations if in rotation mode
            if is_rotation_mode and isinstance(it, (BaseObj, RectangleItem)):
                self._drag.initial_rotations[it] = it.rotation()

        # Mark as group rotation if rotating multiple items
        if is_rotation_mode and len(selected_items) > 1:
            self._drag.is_group_rotation = True

    def _disable_secondary_movable_flags(self) -> None:
        """Disable ItemIsMovable on secondary items to prevent Qt from moving them."""
        for item in self._drag.secondary_items:
            if item.flags() & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable:
                item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                self._drag.items_with_movable_disabled.add(item)

    def _restore_secondary_movable_flags(self) -> None:
        """Restore ItemIsMovable on items that had it disabled."""
        for item in self._drag.items_with_movable_disabled:
            item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self._drag.items_with_movable_disabled.clear()

    def update_group_positions(self) -> None:
        """
        Update positions of all secondary items during drag.

        Uses offset-based positioning: each secondary item is placed at
        primary.pos() + stored_offset. This correctly handles magnetic snap
        by preserving relative positions regardless of where the primary snaps.

        Called from SceneEventHandler on every mouse move during drag.
        """
        if not self._drag.primary_item:
            return

        if not self._drag.is_multi_selection and not self._drag.is_group_drag:
            return

        # Get primary's current position (includes any snap adjustment)
        primary_pos = self._drag.primary_item.pos()

        # Position each secondary item at primary + offset
        for item, offset in self._drag.secondary_offsets.items():
            item.setPos(primary_pos + offset)

    def is_dragging_group(self) -> bool:
        """Check if currently dragging a group or multi-selection."""
        return self._drag.is_group_drag or self._drag.is_multi_selection

    def handle_mouse_release(self) -> bool:
        """
        Handle mouse release - snap to grid, restore flags, and create undo commands.

        Returns:
            True if any commands were created
        """
        from ...core.undo_commands import MoveItemCommand, RotateItemCommand, RotateItemsCommand
        from ...objects import BaseObj, RectangleItem

        # Clear snap guides
        if hasattr(self.view, "clear_snap_guides"):
            self.view.clear_snap_guides()  # type: ignore[attr-defined]

        # Restore movable flags BEFORE creating undo commands
        self._restore_secondary_movable_flags()

        commands_created = False

        # Apply snap to grid and create move commands
        for it, old_pos in self._drag.initial_positions.items():
            if isinstance(it, BaseObj) and self._get_snap_to_grid():
                p = it.pos()
                it.setPos(round(p.x()), round(p.y()))

            # Create move command if item was moved (and not rotated)
            if it not in self._drag.initial_rotations:
                new_pos = it.pos()
                if old_pos != new_pos:
                    move_cmd = MoveItemCommand(it, old_pos, new_pos)
                    self.undo_stack.push(move_cmd)
                    commands_created = True

        # Handle rotation commands
        if self._drag.initial_rotations and not self._drag.is_group_rotation:
            # Single item rotation(s)
            for it, old_rotation in self._drag.initial_rotations.items():
                new_rotation = it.rotation()
                if abs(new_rotation - old_rotation) > 0.01:
                    rot_cmd: RotateItemCommand = RotateItemCommand(it, old_rotation, new_rotation)
                    self.undo_stack.push(rot_cmd)
                    commands_created = True

        elif self._drag.is_group_rotation:
            # Group rotation - use initial_positions and initial_rotations directly
            items = list(self._drag.initial_positions.keys())
            new_positions = {it: it.pos() for it in items}
            new_rotations = {
                it: it.rotation() for it in items if isinstance(it, (BaseObj, RectangleItem))
            }

            # Check if anything actually changed
            position_changed = any(
                self._drag.initial_positions[it] != new_positions[it] for it in items
            )
            rotation_changed = any(
                abs(self._drag.initial_rotations.get(it, 0) - new_rotations.get(it, 0)) > 0.01
                for it in items
                if isinstance(it, (BaseObj, RectangleItem))
            )

            if position_changed or rotation_changed:
                rotatable_items = [it for it in items if isinstance(it, (BaseObj, RectangleItem))]
                if rotatable_items:
                    from PyQt6.QtWidgets import QGraphicsItem

                    rotatable_items_typed: list[QGraphicsItem] = list(rotatable_items)
                    old_positions_typed: dict[QGraphicsItem, QtCore.QPointF] = {
                        it: self._drag.initial_positions[it]
                        for it in rotatable_items
                        if it in self._drag.initial_positions
                    }
                    new_positions_typed: dict[QGraphicsItem, QtCore.QPointF] = {
                        it: new_positions[it]
                        for it in rotatable_items
                        if it in new_positions
                    }
                    old_rotations_typed: dict[QGraphicsItem, float] = {
                        it: self._drag.initial_rotations[it]
                        for it in rotatable_items
                        if it in self._drag.initial_rotations
                    }
                    new_rotations_typed: dict[QGraphicsItem, float] = {
                        it: new_rotations[it]
                        for it in rotatable_items
                        if it in new_rotations
                    }
                    rot_items_cmd: RotateItemsCommand = RotateItemsCommand(
                        rotatable_items_typed,
                        old_positions_typed,
                        new_positions_typed,
                        old_rotations_typed,
                        new_rotations_typed,
                    )
                    self.undo_stack.push(rot_items_cmd)
                    commands_created = True

        # Clear drag state
        self._drag.clear()

        # Schedule retrace
        self._schedule_retrace()

        return commands_created
