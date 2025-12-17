"""
Command pattern implementation for undo/redo functionality.
Each command encapsulates an action that can be executed and undone.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from PyQt6 import QtCore, QtWidgets

from .protocols import Editable, HasParams, Undoable

if TYPE_CHECKING:
    from PyQt6 import QtWidgets

    from .layer_tree_state import LayerTreeState


class Command(ABC):
    """Abstract base class for undoable commands."""

    @abstractmethod
    def execute(self) -> None:
        """Execute the command."""
        pass

    @abstractmethod
    def undo(self) -> None:
        """Undo the command."""
        pass

    def id(self) -> int:
        """Return command ID for merging. Return -1 to disable merging."""
        return -1

    def merge_with(self, other: Command) -> bool:
        """Attempt to merge with another command. Return True if successful."""
        return False


class AddItemCommand(Command):
    """Command to add an item to the scene."""

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        item: QtWidgets.QGraphicsItem,
        layer_state: LayerTreeState | None = None,
    ):
        """
        Initialize AddItemCommand.

        Args:
            scene: The graphics scene to add the item to
            item: The graphics item to add
        """
        self.scene = scene
        self.item = item
        self._layer_state = layer_state
        self._executed = False

    def execute(self) -> None:
        """Add the item to the scene."""
        if not self._executed:
            self.scene.addItem(self.item)
            if self._layer_state and hasattr(self.item, "item_uuid"):
                self._layer_state.add_item(str(self.item.item_uuid), None, 0, emit=True)
            self._executed = True

    def undo(self) -> None:
        """Remove the item from the scene."""
        if self._executed:
            if self._layer_state and hasattr(self.item, "item_uuid"):
                self._layer_state.remove_item(str(self.item.item_uuid), emit=True)
            self.scene.removeItem(self.item)
            self._executed = False


class RemoveItemCommand(Command):
    """Command to remove an item from the scene."""

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        item: QtWidgets.QGraphicsItem,
        layer_state: LayerTreeState | None = None,
    ):
        """
        Initialize RemoveItemCommand.

        Args:
            scene: The graphics scene to remove the item from
            item: The graphics item to remove
            group_manager: Optional group manager for group membership cleanup
        """
        self.scene = scene
        self.item = item
        self._layer_state = layer_state
        self._executed = False

        # Store layer-tree context for undo (item parent/group placement)
        self._item_uuid: str | None = getattr(item, "item_uuid", None)
        self._old_parent_uuid: str | None = None
        self._old_index: int = 0
        if self._layer_state and self._item_uuid:
            node = self._layer_state.get_node(self._item_uuid)
            if node:
                if node.parent:
                    self._old_parent_uuid = node.parent.uuid
                    self._old_index = node.parent.children.index(node)
                else:
                    roots = self._layer_state.get_root_nodes()
                    self._old_index = roots.index(node) if node in roots else 0

    def execute(self) -> None:
        """Remove the item from the scene and its group."""
        if not self._executed:
            # Remove from layer state first (authoritative)
            if self._layer_state and self._item_uuid:
                self._layer_state.remove_item(self._item_uuid, emit=True)
            self.scene.removeItem(self.item)
            self._executed = True

    def undo(self) -> None:
        """Add the item back to the scene and restore group membership."""
        if self._executed:
            self.scene.addItem(self.item)
            if self._layer_state and self._item_uuid:
                # Restore item placement
                if self._old_parent_uuid and self._layer_state.get_node(self._old_parent_uuid):
                    self._layer_state.add_item(self._item_uuid, self._old_parent_uuid, self._old_index, emit=True)
                else:
                    self._layer_state.add_item(self._item_uuid, None, self._old_index, emit=True)
            self._executed = False


class MoveItemCommand(Command):
    """Command to move an item to a new position."""

    def __init__(
        self,
        item: QtWidgets.QGraphicsItem,
        old_pos: QtCore.QPointF,
        new_pos: QtCore.QPointF,
    ):
        """
        Initialize MoveItemCommand.

        Args:
            item: The graphics item to move
            old_pos: The original position
            new_pos: The new position
        """
        self.item = item
        self.old_pos = QtCore.QPointF(old_pos)  # Make a copy
        self.new_pos = QtCore.QPointF(new_pos)  # Make a copy

    def execute(self) -> None:
        """Move the item to the new position."""
        self.item.setPos(self.new_pos)
        # Force Qt to update cached transforms (fixes BeamsplitterItem position tracking)
        self.item.setTransform(self.item.transform())

    def undo(self) -> None:
        """Move the item back to the old position."""
        self.item.setPos(self.old_pos)
        # Force Qt to update cached transforms (fixes BeamsplitterItem position tracking)
        self.item.setTransform(self.item.transform())

    def id(self) -> int:
        """Return unique ID for this item to enable command merging."""
        return id(self.item)

    def merge_with(self, other: Command) -> bool:
        """Merge with another MoveItemCommand for the same item."""
        if not isinstance(other, MoveItemCommand):
            return False
        if other.item is not self.item:
            return False
        # Update new position to include the other command's movement
        self.new_pos = QtCore.QPointF(other.new_pos)
        return True


class AddMultipleItemsCommand(Command):
    """Command to add multiple items to the scene in a single operation."""

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        items: list[QtWidgets.QGraphicsItem],
        layer_state: LayerTreeState | None = None,
    ):
        """
        Initialize AddMultipleItemsCommand.

        Args:
            scene: The graphics scene to add items to
            items: The list of graphics items to add
        """
        self.scene = scene
        self.items = items
        self._layer_state = layer_state
        self._executed = False

    def execute(self) -> None:
        """Add all items to the scene."""
        if not self._executed:
            for item in self.items:
                self.scene.addItem(item)
                if self._layer_state and hasattr(item, "item_uuid"):
                    self._layer_state.add_item(str(item.item_uuid), None, 0, emit=False)
            if self._layer_state:
                self._layer_state.changed.emit()
            self._executed = True

    def undo(self) -> None:
        """Remove all items from the scene."""
        if self._executed:
            if self._layer_state:
                for item in self.items:
                    if hasattr(item, "item_uuid"):
                        self._layer_state.remove_item(str(item.item_uuid), emit=False)
                self._layer_state.changed.emit()
            for item in self.items:
                self.scene.removeItem(item)
            self._executed = False


class RemoveMultipleItemsCommand(Command):
    """Command to remove multiple items from the scene in a single operation."""

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        items: list[QtWidgets.QGraphicsItem],
        layer_state: LayerTreeState | None = None,
    ):
        """
        Initialize RemoveMultipleItemsCommand.

        Args:
            scene: The graphics scene to remove items from
            items: The list of graphics items to remove
            group_manager: Optional group manager for group membership cleanup
        """
        self.scene = scene
        self.items = items
        self._layer_state = layer_state
        self._executed = False

        # Store per-item tree placement for undo
        self._placements: dict[str, tuple[str | None, int]] = {}
        if self._layer_state:
            for item in items:
                item_uuid = getattr(item, "item_uuid", None)
                if not item_uuid:
                    continue
                node = self._layer_state.get_node(item_uuid)
                if node:
                    if node.parent:
                        self._placements[item_uuid] = (node.parent.uuid, node.parent.children.index(node))
                    else:
                        roots = self._layer_state.get_root_nodes()
                        self._placements[item_uuid] = (None, roots.index(node) if node in roots else 0)

    def execute(self) -> None:
        """Remove all items from the scene and their groups."""
        if not self._executed:
            if self._layer_state:
                for item in self.items:
                    item_uuid = getattr(item, "item_uuid", None)
                    if item_uuid:
                        self._layer_state.remove_item(item_uuid, emit=False)
                self._layer_state.changed.emit()
            for item in self.items:
                self.scene.removeItem(item)
            self._executed = True

    def undo(self) -> None:
        """Add all items back to the scene and restore group memberships."""
        if self._executed:
            for item in self.items:
                self.scene.addItem(item)
            if self._layer_state:
                for item in self.items:
                    item_uuid = getattr(item, "item_uuid", None)
                    if not item_uuid:
                        continue
                    parent_uuid, idx = self._placements.get(item_uuid, (None, 0))
                    self._layer_state.add_item(item_uuid, parent_uuid, idx, emit=False)
                self._layer_state.changed.emit()
            self._executed = False


class PasteItemsCommand(Command):
    """Command to paste multiple items to the scene."""

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        items: list[QtWidgets.QGraphicsItem],
        layer_state: LayerTreeState | None = None,
    ):
        """
        Initialize PasteItemsCommand.

        Args:
            scene: The graphics scene to add items to
            items: The list of graphics items to add
        """
        self.scene = scene
        self.items = items
        self._layer_state = layer_state
        self._executed = False

    def execute(self) -> None:
        """Add all items to the scene."""
        if not self._executed:
            for item in self.items:
                self.scene.addItem(item)
                if self._layer_state and hasattr(item, "item_uuid"):
                    self._layer_state.add_item(str(item.item_uuid), None, 0, emit=False)
            if self._layer_state:
                self._layer_state.changed.emit()
            self._executed = True

    def undo(self) -> None:
        """Remove all items from the scene."""
        if self._executed:
            if self._layer_state:
                for item in self.items:
                    if hasattr(item, "item_uuid"):
                        self._layer_state.remove_item(str(item.item_uuid), emit=False)
                self._layer_state.changed.emit()
            for item in self.items:
                self.scene.removeItem(item)
            self._executed = False


class PropertyChangeCommand(Command):
    """Command to change properties of an item using memento pattern."""

    def __init__(
        self,
        item: Undoable,
        before_state: dict[str, Any],
        after_state: dict[str, Any],
    ):
        """
        Initialize PropertyChangeCommand.

        Args:
            item: The item whose properties changed (must implement Undoable protocol)
            before_state: Dictionary of property values before the change
            after_state: Dictionary of property values after the change
        """
        self.item = item
        self.before_state = before_state
        self.after_state = after_state

    def execute(self) -> None:
        """Apply the after state to the item."""
        self._apply_state(self.after_state)

    def undo(self) -> None:
        """Restore the before state to the item."""
        self._apply_state(self.before_state)

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Apply a state dictionary to the item."""
        # Try custom apply_state method first (Undoable protocol)
        if isinstance(self.item, Undoable):
            self.item.apply_state(state)
            return

        # Fallback: apply each key-value pair
        for key, value in state.items():
            if key == "pos":
                self.item.setPos(QtCore.QPointF(value["x"], value["y"]))
            elif key == "rotation":
                self.item.setRotation(value)
            elif isinstance(self.item, HasParams):
                # For items with params dataclass
                if hasattr(self.item.params, key):
                    setattr(self.item.params, key, value)

        # Trigger updates
        if isinstance(self.item, HasParams):
            self.item._sync_params_from_item()
        if isinstance(self.item, Editable):
            self.item.edited.emit()
        # All QGraphicsItems have update() - no hasattr check needed
        self.item.update()


class RotateItemCommand(Command):
    """Command to rotate an item to a new angle."""

    def __init__(
        self,
        item: QtWidgets.QGraphicsItem,
        old_rotation: float,
        new_rotation: float,
    ):
        """
        Initialize RotateItemCommand.

        Args:
            item: The graphics item to rotate
            old_rotation: The original rotation in degrees
            new_rotation: The new rotation in degrees
        """
        self.item = item
        self.old_rotation = old_rotation
        self.new_rotation = new_rotation

    def execute(self) -> None:
        """Rotate the item to the new angle."""
        self.item.setRotation(self.new_rotation)

    def undo(self) -> None:
        """Rotate the item back to the old angle."""
        self.item.setRotation(self.old_rotation)


class RotateItemsCommand(Command):
    """Command to rotate multiple items together (group rotation)."""

    def __init__(
        self,
        items: list[QtWidgets.QGraphicsItem],
        old_positions: dict[QtWidgets.QGraphicsItem, QtCore.QPointF],
        new_positions: dict[QtWidgets.QGraphicsItem, QtCore.QPointF],
        old_rotations: dict[QtWidgets.QGraphicsItem, float],
        new_rotations: dict[QtWidgets.QGraphicsItem, float],
    ):
        """
        Initialize RotateItemsCommand for group rotation.

        Args:
            items: The list of graphics items to rotate
            old_positions: Dict mapping items to their original positions
            new_positions: Dict mapping items to their new positions
            old_rotations: Dict mapping items to their original rotations
            new_rotations: Dict mapping items to their new rotations
        """
        self.items = items
        self.old_positions = {item: QtCore.QPointF(pos) for item, pos in old_positions.items()}
        self.new_positions = {item: QtCore.QPointF(pos) for item, pos in new_positions.items()}
        self.old_rotations = dict(old_rotations)
        self.new_rotations = dict(new_rotations)

    def execute(self) -> None:
        """Apply new positions and rotations to all items."""
        for item in self.items:
            item.setPos(self.new_positions[item])
            item.setRotation(self.new_rotations[item])

    def undo(self) -> None:
        """Restore old positions and rotations for all items."""
        for item in self.items:
            item.setPos(self.old_positions[item])
            item.setRotation(self.old_rotations[item])


class ZOrderCommand(Command):
    """Command to change z-order (stacking order) of items."""

    def __init__(
        self,
        items: list[QtWidgets.QGraphicsItem],
        old_z_values: dict[QtWidgets.QGraphicsItem, float],
        new_z_values: dict[QtWidgets.QGraphicsItem, float],
    ):
        """
        Initialize ZOrderCommand.

        Args:
            items: The list of graphics items to change z-order for
            old_z_values: Dict mapping items to their original z-values
            new_z_values: Dict mapping items to their new z-values
        """
        self.items = items
        self.old_z_values = dict(old_z_values)
        self.new_z_values = dict(new_z_values)

    def execute(self) -> None:
        """Apply new z-values to all items."""
        for item in self.items:
            item.setZValue(self.new_z_values[item])

    def undo(self) -> None:
        """Restore old z-values for all items."""
        for item in self.items:
            item.setZValue(self.old_z_values[item])


class BatchCommand(Command):
    """Execute multiple Commands as one undo/redo step."""

    def __init__(self, commands: list[Command]):
        self._commands = [c for c in commands if c is not None]

    def execute(self) -> None:
        for cmd in self._commands:
            cmd.execute()

    def undo(self) -> None:
        for cmd in reversed(self._commands):
            cmd.undo()


class MoveNodeCommand(Command):
    """Command to move a single node to a new parent/index in LayerTreeState."""

    def __init__(
        self,
        layer_state: LayerTreeState,
        uuid: str,
        target_parent_uuid: str | None,
        target_index: int,
    ):
        self._layer_state = layer_state
        self._uuid = uuid
        self._new_parent_uuid = target_parent_uuid
        self._new_index = target_index

        old = layer_state.get_parent_and_index(uuid)
        if old:
            self._old_parent_uuid, self._old_index = old
        else:
            self._old_parent_uuid, self._old_index = None, 0

    def execute(self) -> None:
        self._layer_state.move_node(self._uuid, self._new_parent_uuid, self._new_index, emit=True)

    def undo(self) -> None:
        self._layer_state.move_node(self._uuid, self._old_parent_uuid, self._old_index, emit=True)


# =============================================================================
# Group Commands
# =============================================================================


class CreateGroupCommand(Command):
    """Command to create a new group in LayerTreeState."""

    def __init__(
        self,
        layer_state: LayerTreeState,
        name: str,
        item_uuids: list[str],
        parent_group_uuid: str | None = None,
    ):
        """
        Initialize CreateGroupCommand.

        Args:
            group_manager: The group manager to use
            name: Name of the group
            item_uuids: List of item UUIDs to add to the group
            parent_group_uuid: Optional parent group UUID for nested groups
        """
        self._layer_state = layer_state
        self._name = name
        self._item_uuids = list(item_uuids)
        self._parent_group_uuid = parent_group_uuid
        self._group_uuid: str | None = None
        self._executed = False
        # Capture original placements for undo
        self._original_positions: dict[str, tuple[str | None, int]] = {}
        for uuid in self._item_uuids:
            pos = layer_state.get_parent_and_index(uuid)
            if pos:
                self._original_positions[uuid] = pos
        # Insert group where the first item currently sits within the target parent (when applicable)
        self._insert_index: int = 0
        if self._item_uuids:
            first_pos = layer_state.get_parent_and_index(self._item_uuids[0])
            if first_pos and first_pos[0] == parent_group_uuid:
                self._insert_index = first_pos[1]

    def execute(self) -> None:
        """Create the group."""
        if not self._executed:
            # Create empty group node
            self._group_uuid = self._layer_state.create_group(
                self._name,
                parent_group_uuid=self._parent_group_uuid,
                index=self._insert_index,
                group_uuid=self._group_uuid,
                emit=False,
            )
            # Move items into it (preserving their current relative order by applying in order)
            for uuid in self._item_uuids:
                self._layer_state.move_item_to_group(uuid, self._group_uuid, emit=False)
            self._layer_state.changed.emit()
            self._executed = True

    def undo(self) -> None:
        """Delete the group and restore items to their original placements."""
        if self._executed and self._group_uuid:
            self._layer_state.delete_group(self._group_uuid, emit=False)
            for uuid, (parent_uuid, idx) in self._original_positions.items():
                if self._layer_state.get_node(uuid):
                    self._layer_state.move_node(uuid, parent_uuid, idx, emit=False)
                else:
                    self._layer_state.add_item(uuid, parent_uuid, idx, emit=False)
            self._layer_state.changed.emit()
            self._executed = False


class DeleteGroupCommand(Command):
    """Command to delete a group in LayerTreeState."""

    def __init__(
        self,
        layer_state: LayerTreeState,
        group_uuid: str,
        keep_items: bool = True,
    ):
        """
        Initialize DeleteGroupCommand.

        Args:
            group_manager: The group manager to use
            group_uuid: UUID of the group to delete
            keep_items: If True, items remain in scene (ungrouped)
        """
        self._layer_state = layer_state
        self._group_uuid = group_uuid
        self._keep_items = keep_items
        self._old_parent_uuid: str | None = None
        self._old_index: int = 0
        # Snapshot group subtree for undo
        node = layer_state.get_node(group_uuid)
        self._snapshot: dict[str, Any] | None = None
        if node and node.is_group():
            old = layer_state.get_parent_and_index(group_uuid)
            if old:
                self._old_parent_uuid, self._old_index = old
            # serialize just this subtree
            def node_to_dict(n):
                d = {"uuid": n.uuid, "type": n.node_type}
                if n.name is not None:
                    d["name"] = n.name
                if n.collapsed:
                    d["collapsed"] = True
                if n.children:
                    d["children"] = [node_to_dict(c) for c in n.children]
                return d
            self._snapshot = node_to_dict(node)

    def execute(self) -> None:
        """Delete the group (works for both initial execute and redo)."""
        if not self._snapshot:
            return
        if self._layer_state.get_node(self._group_uuid):
            if self._keep_items:
                self._layer_state.delete_group(self._group_uuid, emit=True)
            else:
                # If deleting items too, caller must remove from scene separately.
                self._layer_state.delete_group(self._group_uuid, emit=True)

    def undo(self) -> None:
        """Restore the group."""
        if not self._snapshot:
            return
        # Recreate group subtree (UUID-preserving) at original location
        tmp = LayerTreeState.from_dict({"version": 1, "nodes": [self._snapshot]})
        root = tmp.get_root_nodes()[0] if tmp.get_root_nodes() else None
        if not root:
            return
        # Add group node (UUID preserved)
        self._layer_state.create_group(
            root.name or "Group",
            parent_group_uuid=self._old_parent_uuid,
            index=self._old_index,
            group_uuid=root.uuid,
            emit=False,
        )
        self._layer_state.set_group_collapsed(root.uuid, root.collapsed, emit=False)
        # Add children recursively
        def add_children(parent_uuid: str, children):
            for ch in children:
                if ch["type"] == "group":
                    gid = ch["uuid"]
                    self._layer_state.create_group(ch.get("name", "Group"), parent_group_uuid=parent_uuid, group_uuid=gid, emit=False)
                    self._layer_state.set_group_collapsed(gid, bool(ch.get("collapsed", False)), emit=False)
                    add_children(gid, ch.get("children", []) or [])
                else:
                    self._layer_state.add_item(ch["uuid"], parent_uuid, index=10**9, emit=False)
        add_children(root.uuid, self._snapshot.get("children", []) or [])
        self._layer_state.changed.emit()
