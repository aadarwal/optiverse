"""
Handler for item drag, move, and rotation tracking.

Extracts position/rotation tracking and undo command creation from MainWindow.
Supports group movement where all items in a group move together.

Architecture:
- The scene event filter takes FULL CONTROL of all non-Ctrl left-button item drags.
  Press, move, and release events are consumed — Qt never sets up its own drag.
- Ctrl+click rotation is tracked for undo but NOT consumed; BaseObj handles it.
- Secondary items have ItemIsMovable disabled during drag (no magnetic snap on them).
- Primary item keeps ItemIsMovable so setPos() triggers magnetic snap via itemChange.
- No class-level global state — all state is instance-scoped in DragContext.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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

    # The item being directly dragged by the mouse (None = no drag active)
    primary_item: QtWidgets.QGraphicsItem | None = None

    # Initial positions of all dragged items (for undo)
    initial_positions: dict[QtWidgets.QGraphicsItem, QtCore.QPointF] = field(
        default_factory=dict
    )

    # Initial rotations (for rotation tracking — Ctrl+click path only)
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

    # Whether this is a group rotation (multiple items rotating together)
    is_group_rotation: bool = False

    # Offset from mouse scene pos to primary item pos at press time.
    # Used to compute primary's expected position during drag.
    press_offset: QtCore.QPointF = field(default_factory=lambda: QtCore.QPointF())

    # True when only tracking rotation (Ctrl+click), not dragging.
    # primary_item is NOT set in this mode — is_dragging() returns False.
    rotation_only: bool = False

    # Non-empty when dragging a linked assembly as a whole.
    link_uuid: str | None = None

    # Items with _group_drag_override set True (must be cleared on drag end)
    group_drag_override_items: set[QtWidgets.QGraphicsItem] = field(
        default_factory=set
    )

    def clear(self) -> None:
        """Reset all drag state."""
        self._clear_group_drag_overrides()
        self.primary_item = None
        self.initial_positions.clear()
        self.initial_rotations.clear()
        self.secondary_items.clear()
        self.secondary_offsets.clear()
        self.items_with_movable_disabled.clear()
        self.is_group_rotation = False
        self.press_offset = QtCore.QPointF()
        self.rotation_only = False
        self.link_uuid = None

    def _clear_group_drag_overrides(self) -> None:
        """Reset _group_drag_override on all items that had it set."""
        for item in self.group_drag_override_items:
            if hasattr(item, "_group_drag_override"):
                item._group_drag_override = False  # type: ignore[attr-defined]
        self.group_drag_override_items.clear()


class ItemDragHandler:
    """
    Handles item dragging, position tracking, and rotation for undo/redo support.

    The event filter takes FULL CONTROL of all non-Ctrl item drags:
      - handle_drag_start()  → on press: finds item, sets up state, returns True to consume
      - handle_drag_move()   → on move: positions primary + secondaries
      - handle_drag_end()    → on release: snaps to grid, creates undo commands

    Rotation (Ctrl+click) is NOT consumed — BaseObj handles the interactive rotation.
    We just track initial state and create undo commands on release:
      - start_rotation_tracking() → on Ctrl+press
      - handle_rotation_end()     → on release
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
        self.scene = scene
        self.view = view
        self.undo_stack = undo_stack
        self._get_snap_to_grid = snap_to_grid_getter
        self._schedule_retrace = schedule_retrace
        self._layer_state = layer_state

        # All drag state encapsulated in DragContext
        self._drag = DragContext()

    # ------------------------------------------------------------------
    # Public API: drag (non-Ctrl left-button)
    # ------------------------------------------------------------------

    def handle_drag_start(
        self, scene_pos: QtCore.QPointF, modifiers: QtCore.Qt.KeyboardModifier
    ) -> bool:
        """
        Set up drag state on left-button press (non-Ctrl).

        Returns True if an item was found and drag was started — caller must
        call ev.accept() and return True to consume the event. Returns False
        if no item was found or the event should pass through to Qt.
        """
        from ...objects import BaseObj, RectangleItem
        from ...objects.annotations import RulerItem, TextNoteItem
        from ...objects.annotations.angle_measure_item import AngleMeasureItem

        # Clean up any leftover state from a previous drag
        self._restore_secondary_movable_flags()
        self._drag.clear()

        # ---- Find item under mouse ----
        clicked_item = self.scene.itemAt(scene_pos, QtGui.QTransform())

        # Walk up parent hierarchy to find the actual draggable item
        draggable_item: QtWidgets.QGraphicsItem | None = None
        while clicked_item is not None:
            if isinstance(
                clicked_item, (BaseObj, RulerItem, TextNoteItem, RectangleItem, AngleMeasureItem)
            ):
                draggable_item = clicked_item
                break
            clicked_item = clicked_item.parentItem()

        if draggable_item is None:
            # No item under mouse — let Qt handle (rubber band selection)
            return False

        # ---- RulerItem endpoint check ----
        # If clicking near a ruler endpoint, let RulerItem handle its own grab mode
        if isinstance(draggable_item, RulerItem):
            local_pos = draggable_item.mapFromScene(scene_pos)
            if draggable_item._nearest_point(local_pos) is not None:
                return False

        # ---- AngleMeasureItem handle check ----
        # If clicking near a vertex/point handle, let AngleMeasureItem handle its own drag
        if isinstance(draggable_item, AngleMeasureItem):
            if draggable_item._point_at_pos(scene_pos) is not None:
                return False

        # ---- Check linked group membership ----
        linked_group = self._find_linked_group(draggable_item)
        if linked_group is not None:
            group_uuid, node = linked_group
            if node.link_metadata and node.link_metadata.editing:
                pass  # editing mode — treat as normal individual drag below
            else:
                return self._start_linked_group_drag(
                    draggable_item, group_uuid, scene_pos,
                )

        # ---- Reject non-selectable items ----
        if not (draggable_item.flags() & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable):
            return False

        # ---- Handle selection ----
        # Since we consume the press event, Qt won't handle selection.
        # We do it manually to keep the layer panel and visual feedback in sync.
        is_shift = bool(modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier)

        if is_shift:
            # Shift+click: toggle this item's selection
            if draggable_item.isSelected():
                # Deselecting — don't start a drag
                draggable_item.setSelected(False)
                return False
            else:
                # Add to selection (keep existing selected items)
                draggable_item.setSelected(True)
        elif draggable_item.isSelected():
            # Already selected (e.g. part of multi-selection from layers panel)
            # — keep current selection, just drag them all
            pass
        else:
            # Clicking an unselected item: clear selection, select only this one
            self.scene.clearSelection()
            draggable_item.setSelected(True)

        self._drag.primary_item = draggable_item

        # ---- Build the set of items to drag ----
        selected_items = [
            it
            for it in self.scene.selectedItems()
            if isinstance(
                it, (BaseObj, RulerItem, TextNoteItem, RectangleItem, AngleMeasureItem)
            )
        ]

        # ---- Group-relative-lock expansion ----
        # When a locked item in an unlocked group is clicked, expand the drag
        # to include all items in the immediate parent group so that the entire
        # group moves as a unit while preserving relative positions.
        if (
            self._layer_state
            and hasattr(draggable_item, "item_uuid")
            and getattr(draggable_item, "_locked", False)
        ):
            group_uuid = self._layer_state.get_group_for_item(draggable_item.item_uuid)
            if group_uuid and not self._layer_state.is_effectively_locked(group_uuid):
                existing = {
                    it.item_uuid for it in selected_items if hasattr(it, "item_uuid")
                }
                for child_uuid in self._layer_state.get_group_items_recursive(group_uuid):
                    if child_uuid not in existing:
                        child_item = self._find_scene_item(child_uuid)
                        if child_item is not None:
                            selected_items.append(child_item)
                            existing.add(child_uuid)
                # Set override on all locked items in the expanded set
                for it in selected_items:
                    if getattr(it, "_locked", False) and hasattr(it, "_group_drag_override"):
                        it._group_drag_override = True  # type: ignore[attr-defined]
                        self._drag.group_drag_override_items.add(it)

        # ---- Store press offset ----
        self._drag.press_offset = scene_pos - draggable_item.pos()

        # ---- Identify secondary items and calculate offsets ----
        primary_pos = draggable_item.pos()
        for item in selected_items:
            if item is not draggable_item:
                self._drag.secondary_items.append(item)
                self._drag.secondary_offsets[item] = item.pos() - primary_pos

        # Disable ItemIsMovable on secondary items so setPos() skips magnetic snap
        if self._drag.secondary_items:
            self._disable_secondary_movable_flags()

        # ---- Store initial positions for undo ----
        for it in selected_items:
            self._drag.initial_positions[it] = QtCore.QPointF(it.pos())

        return True

    def handle_drag_move(self, scene_pos: QtCore.QPointF) -> None:
        """
        Move primary + secondary items during drag.

        Computes the primary item's intended position from the mouse event
        and moves ALL items in a single step. setPos() on the primary triggers
        BaseObj.itemChange → magnetic snap. Secondary items are positioned at
        primary_pos + stored offset (no snap for them).

        For single-item drags, secondary_offsets is empty — only the primary moves.
        """
        if not self._drag.primary_item:
            return

        # Compute where the primary item should be from the mouse position
        intended_pos = scene_pos - self._drag.press_offset
        self._drag.primary_item.setPos(intended_pos)

        # Read back the actual position (may differ due to magnetic snap)
        primary_pos = self._drag.primary_item.pos()

        # Position each secondary item at primary + offset
        for item, offset in self._drag.secondary_offsets.items():
            item.setPos(primary_pos + offset)

    def handle_drag_end(self) -> bool:
        """
        Finalize drag — snap to grid, create undo commands, clear state.

        Returns True if any undo commands were created.
        """
        from ...core.undo_commands import BatchCommand, MoveItemCommand
        from ...objects import BaseObj

        # Restore movable flags BEFORE creating undo commands
        self._restore_secondary_movable_flags()

        commands_created = False
        is_linked = self._drag.link_uuid is not None

        # Apply snap to grid and collect move commands
        move_commands: list = []
        for it, old_pos in self._drag.initial_positions.items():
            if not is_linked and isinstance(it, BaseObj) and self._get_snap_to_grid():
                from ...core import preferences

                g = preferences.grid_snap_size_mm
                p = it.pos()
                it.setPos(round(p.x() / g) * g, round(p.y() / g) * g)

            new_pos = it.pos()
            if old_pos != new_pos:
                move_commands.append(MoveItemCommand(it, old_pos, new_pos))

        # For linked group drags, also update LinkMetadata offsets
        if is_linked and move_commands and self._layer_state:
            offset_cmd = self._build_link_offset_command()
            if offset_cmd:
                move_commands.append(offset_cmd)

        # Push move commands — batch multiple into a single undo step
        if move_commands:
            if len(move_commands) == 1:
                self.undo_stack.push(move_commands[0])
            else:
                self.undo_stack.push(BatchCommand(move_commands))
            commands_created = True

        # Clear drag state
        self._drag.clear()

        # Schedule retrace
        self._schedule_retrace()

        # Clear snap guides AFTER all setPos calls (grid snap, undo push) that
        # can re-trigger magnetic snap via BaseObj.itemChange.
        if hasattr(self.view, "clear_snap_guides"):
            self.view.clear_snap_guides()  # type: ignore[attr-defined]

        return commands_created

    def is_dragging(self) -> bool:
        """True if any drag (single or group) is active."""
        return self._drag.primary_item is not None and not self._drag.rotation_only

    # ------------------------------------------------------------------
    # Public API: rotation tracking (Ctrl+click — NOT consumed)
    # ------------------------------------------------------------------

    def start_rotation_tracking(
        self, scene_pos: QtCore.QPointF, modifiers: QtCore.Qt.KeyboardModifier
    ) -> None:
        """
        Record initial positions/rotations for undo on Ctrl+click.

        The interactive rotation is handled by BaseObj.mousePressEvent / mouseMoveEvent.
        We just snapshot state here so we can create undo commands on release.
        """
        from ...objects import BaseObj, RectangleItem
        from ...objects.annotations import RulerItem, TextNoteItem
        from ...objects.annotations.angle_measure_item import AngleMeasureItem

        # Clean up any leftover state
        self._restore_secondary_movable_flags()
        self._drag.clear()
        self._drag.rotation_only = True

        # Get currently selected items (these are the ones being rotated)
        selected_items = [
            it
            for it in self.scene.selectedItems()
            if isinstance(
                it, (BaseObj, RulerItem, TextNoteItem, RectangleItem, AngleMeasureItem)
            )
        ]

        if not selected_items:
            return

        # Store initial positions and rotations for all rotatable items
        for it in selected_items:
            self._drag.initial_positions[it] = QtCore.QPointF(it.pos())
            if isinstance(it, (BaseObj, RectangleItem, TextNoteItem, RulerItem, AngleMeasureItem)):
                self._drag.initial_rotations[it] = it.rotation()

        # Mark as group rotation if multiple items
        if len(selected_items) > 1:
            self._drag.is_group_rotation = True

    def is_rotation_tracked(self) -> bool:
        """True if rotation tracking is active (Ctrl+click path)."""
        return self._drag.rotation_only and bool(self._drag.initial_rotations)

    def handle_rotation_end(self) -> bool:
        """
        Create rotation undo commands on release after Ctrl+drag.

        Returns True if any rotation commands were created.
        """
        from ...core.undo_commands import RotateItemCommand, RotateItemsCommand
        from ...objects import BaseObj, RectangleItem
        from ...objects.annotations import RulerItem, TextNoteItem
        from ...objects.annotations.angle_measure_item import AngleMeasureItem

        _rotatable = (BaseObj, RectangleItem, TextNoteItem, RulerItem, AngleMeasureItem)
        commands_created = False

        if self._drag.initial_rotations and not self._drag.is_group_rotation:
            # Single item rotation(s)
            for it, old_rotation in self._drag.initial_rotations.items():
                new_rotation = it.rotation()
                if abs(new_rotation - old_rotation) > 0.01:
                    rot_cmd = RotateItemCommand(it, old_rotation, new_rotation)
                    self.undo_stack.push(rot_cmd)
                    commands_created = True

        elif self._drag.is_group_rotation:
            # Group rotation
            items = list(self._drag.initial_positions.keys())
            new_positions = {it: it.pos() for it in items}
            new_rotations = {
                it: it.rotation()
                for it in items
                if isinstance(it, _rotatable)
            }

            # Check if anything actually changed
            position_changed = any(
                self._drag.initial_positions[it] != new_positions[it] for it in items
            )
            rotation_changed = any(
                abs(self._drag.initial_rotations.get(it, 0) - new_rotations.get(it, 0))
                > 0.01
                for it in items
                if isinstance(it, _rotatable)
            )

            if position_changed or rotation_changed:
                rotatable_items = [
                    it for it in items if isinstance(it, _rotatable)
                ]
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
                    rot_items_cmd = RotateItemsCommand(
                        rotatable_items_typed,
                        old_positions_typed,
                        new_positions_typed,
                        old_rotations_typed,
                        new_rotations_typed,
                    )
                    self.undo_stack.push(rot_items_cmd)
                    commands_created = True

        # Clear state
        self._drag.clear()

        # Schedule retrace
        self._schedule_retrace()

        # Clear snap guides (group rotation setPos calls can trigger magnetic snap)
        if hasattr(self.view, "clear_snap_guides"):
            self.view.clear_snap_guides()  # type: ignore[attr-defined]

        return commands_created

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _disable_secondary_movable_flags(self) -> None:
        """Disable ItemIsMovable on secondary items to prevent Qt from moving them."""
        for item in self._drag.secondary_items:
            if item.flags() & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable:
                item.setFlag(
                    QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False
                )
                self._drag.items_with_movable_disabled.add(item)

    def _restore_secondary_movable_flags(self) -> None:
        """Restore ItemIsMovable on items that had it disabled, and clear overrides."""
        for item in self._drag.items_with_movable_disabled:
            item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self._drag.items_with_movable_disabled.clear()
        self._drag._clear_group_drag_overrides()

    # ------------------------------------------------------------------
    # Linked-group helpers
    # ------------------------------------------------------------------

    def _build_link_offset_command(self):
        """Create an undo command that updates LinkMetadata offsets for the drag delta."""
        from ...core.undo_commands import UpdateLinkOffsetCommand

        if not self._layer_state or not self._drag.link_uuid or not self._drag.primary_item:
            return None
        node = self._layer_state.get_node(self._drag.link_uuid)
        if not node or not node.link_metadata:
            return None

        old_pos = self._drag.initial_positions.get(self._drag.primary_item)
        if old_pos is None:
            return None
        new_pos = self._drag.primary_item.pos()
        delta_x = new_pos.x() - old_pos.x()
        delta_y = new_pos.y() - old_pos.y()
        if abs(delta_x) < 1e-9 and abs(delta_y) < 1e-9:
            return None

        meta = node.link_metadata
        old_offset = (meta.offset_x, meta.offset_y)
        new_offset = (meta.offset_x + delta_x, meta.offset_y + delta_y)
        meta.offset_x = new_offset[0]
        meta.offset_y = new_offset[1]

        return UpdateLinkOffsetCommand(
            self._layer_state, self._drag.link_uuid, old_offset, new_offset,
        )

    # ------------------------------------------------------------------
    # Linked-group detection helpers
    # ------------------------------------------------------------------

    def _find_linked_group(
        self, item: QtWidgets.QGraphicsItem,
    ) -> tuple[str, object] | None:
        """If *item* belongs to a linked assembly group, return (group_uuid, node)."""
        if not self._layer_state:
            return None
        item_uuid = getattr(item, "item_uuid", None)
        if not item_uuid:
            return None
        group_uuid = self._layer_state.get_group_for_item(item_uuid)
        if not group_uuid:
            return None
        node = self._layer_state.get_node(group_uuid)
        if node and node.is_linked():
            return group_uuid, node
        return None

    def _find_scene_item(self, item_uuid: str) -> QtWidgets.QGraphicsItem | None:
        """Find a scene item by its item_uuid attribute."""
        for scene_item in self.scene.items():
            if getattr(scene_item, "item_uuid", None) == item_uuid:
                return scene_item
        return None

    def _start_linked_group_drag(
        self,
        clicked_item: QtWidgets.QGraphicsItem,
        group_uuid: str,
        scene_pos: QtCore.QPointF,
    ) -> bool:
        """Set up a drag that moves all items in a linked group as a rigid body."""
        if not self._layer_state:
            return False

        item_uuids = self._layer_state.get_group_items_recursive(group_uuid)
        group_items: list[QtWidgets.QGraphicsItem] = []
        for uid in item_uuids:
            for scene_item in self.scene.items():
                if getattr(scene_item, "item_uuid", None) == uid:
                    group_items.append(scene_item)
                    break

        if not group_items:
            return False

        self._drag.primary_item = clicked_item
        self._drag.link_uuid = group_uuid
        self._drag.press_offset = scene_pos - clicked_item.pos()

        primary_pos = clicked_item.pos()
        for item in group_items:
            self._drag.initial_positions[item] = QtCore.QPointF(item.pos())
            if item is not clicked_item:
                self._drag.secondary_items.append(item)
                self._drag.secondary_offsets[item] = item.pos() - primary_pos

        return True
