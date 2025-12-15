"""
Command pattern implementation for undo/redo functionality.
Each command encapsulates an action that can be executed and undone.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from PyQt6 import QtCore

from .protocols import Editable, HasParams, Undoable

if TYPE_CHECKING:
    from PyQt6 import QtWidgets

    from .layer_group import GroupManager


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

    def __init__(self, scene: QtWidgets.QGraphicsScene, item: QtWidgets.QGraphicsItem):
        """
        Initialize AddItemCommand.

        Args:
            scene: The graphics scene to add the item to
            item: The graphics item to add
        """
        self.scene = scene
        self.item = item
        self._executed = False

    def execute(self) -> None:
        """Add the item to the scene."""
        if not self._executed:
            self.scene.addItem(self.item)
            self._executed = True

    def undo(self) -> None:
        """Remove the item from the scene."""
        if self._executed:
            self.scene.removeItem(self.item)
            self._executed = False


class RemoveItemCommand(Command):
    """Command to remove an item from the scene."""

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        item: QtWidgets.QGraphicsItem,
        group_manager: GroupManager | None = None,
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
        self._group_manager = group_manager
        self._executed = False

        # Store group membership and full group data for undo support
        self._group_uuid: str | None = None
        self._group_data: dict[str, Any] | None = None
        if group_manager and hasattr(item, "item_uuid"):
            group = group_manager.get_item_group(item.item_uuid)
            if group:
                self._group_uuid = group.group_uuid
                # Store full group data in case it gets auto-deleted
                self._group_data = group.to_dict()

    def execute(self) -> None:
        """Remove the item from the scene and its group."""
        if not self._executed:
            # Remove from group first (triggers auto-delete if empty)
            if self._group_manager and hasattr(self.item, "item_uuid"):
                self._group_manager.remove_item_from_group(self.item.item_uuid)
            self.scene.removeItem(self.item)
            self._executed = True

    def undo(self) -> None:
        """Add the item back to the scene and restore group membership."""
        if self._executed:
            self.scene.addItem(self.item)
            # Restore group membership (recreate group if it was auto-deleted)
            if self._group_manager and self._group_uuid and hasattr(self.item, "item_uuid"):
                # Recreate group if it was auto-deleted
                if not self._group_manager.get_group(self._group_uuid) and self._group_data:
                    from .layer_group import LayerGroup

                    group = LayerGroup.from_dict(self._group_data)
                    self._group_manager.add_group(group)

                # Add item back to group
                self._group_manager.add_item_to_group(self.item.item_uuid, self._group_uuid)
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

    def __init__(self, scene: QtWidgets.QGraphicsScene, items: list[QtWidgets.QGraphicsItem]):
        """
        Initialize AddMultipleItemsCommand.

        Args:
            scene: The graphics scene to add items to
            items: The list of graphics items to add
        """
        self.scene = scene
        self.items = items
        self._executed = False

    def execute(self) -> None:
        """Add all items to the scene."""
        if not self._executed:
            for item in self.items:
                self.scene.addItem(item)
            self._executed = True

    def undo(self) -> None:
        """Remove all items from the scene."""
        if self._executed:
            for item in self.items:
                self.scene.removeItem(item)
            self._executed = False


class RemoveMultipleItemsCommand(Command):
    """Command to remove multiple items from the scene in a single operation."""

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        items: list[QtWidgets.QGraphicsItem],
        group_manager: GroupManager | None = None,
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
        self._group_manager = group_manager
        self._executed = False

        # Store group memberships and full group data for undo support
        self._item_groups: dict[str, str] = {}  # item_uuid -> group_uuid
        self._group_data: dict[str, dict[str, Any]] = {}  # group_uuid -> group data
        if group_manager:
            for item in items:
                if hasattr(item, "item_uuid"):
                    group = group_manager.get_item_group(item.item_uuid)
                    if group:
                        self._item_groups[item.item_uuid] = group.group_uuid
                        # Store full group data (avoid duplicates)
                        if group.group_uuid not in self._group_data:
                            self._group_data[group.group_uuid] = group.to_dict()

    def execute(self) -> None:
        """Remove all items from the scene and their groups."""
        if not self._executed:
            # Remove from groups first (triggers auto-delete if empty)
            if self._group_manager:
                for item in self.items:
                    if hasattr(item, "item_uuid"):
                        self._group_manager.remove_item_from_group(item.item_uuid)
            for item in self.items:
                self.scene.removeItem(item)
            self._executed = True

    def undo(self) -> None:
        """Add all items back to the scene and restore group memberships."""
        if self._executed:
            for item in self.items:
                self.scene.addItem(item)
            # Restore group memberships (recreate groups if they were auto-deleted)
            if self._group_manager:
                # First, recreate any auto-deleted groups
                for group_uuid, group_data in self._group_data.items():
                    if not self._group_manager.get_group(group_uuid):
                        from .layer_group import LayerGroup

                        group = LayerGroup.from_dict(group_data)
                        self._group_manager.add_group(group)

                # Then restore item memberships
                for item in self.items:
                    if hasattr(item, "item_uuid"):
                        item_group_uuid: str | None = self._item_groups.get(item.item_uuid)
                        if item_group_uuid:
                            self._group_manager.add_item_to_group(item.item_uuid, item_group_uuid)
            self._executed = False


class PasteItemsCommand(Command):
    """Command to paste multiple items to the scene."""

    def __init__(self, scene: QtWidgets.QGraphicsScene, items: list[QtWidgets.QGraphicsItem]):
        """
        Initialize PasteItemsCommand.

        Args:
            scene: The graphics scene to add items to
            items: The list of graphics items to add
        """
        self.scene = scene
        self.items = items
        self._executed = False

    def execute(self) -> None:
        """Add all items to the scene."""
        if not self._executed:
            for item in self.items:
                self.scene.addItem(item)
            self._executed = True

    def undo(self) -> None:
        """Remove all items from the scene."""
        if self._executed:
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


# =============================================================================
# Group Commands
# =============================================================================


class CreateGroupCommand(Command):
    """Command to create a new group."""

    def __init__(
        self,
        group_manager: GroupManager,
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
        from .layer_group import LayerGroup

        self._group_manager = group_manager
        self._name = name
        self._item_uuids = list(item_uuids)
        self._parent_group_uuid = parent_group_uuid
        self._group: LayerGroup | None = None
        self._executed = False

    def execute(self) -> None:
        """Create the group."""
        if not self._executed:
            if self._group:
                # Re-add an existing group (redo case)
                # First remove items from parent group if this is a subgroup
                if self._parent_group_uuid:
                    parent = self._group_manager.get_group(self._parent_group_uuid)
                    if parent:
                        for item_uuid in self._item_uuids:
                            if item_uuid in parent.item_uuids:
                                parent.item_uuids.remove(item_uuid)
                self._group_manager.add_group(self._group)
            else:
                # First time creation
                self._group = self._group_manager.create_group(
                    self._name, self._item_uuids, self._parent_group_uuid
                )
            self._executed = True

    def undo(self) -> None:
        """Delete the group and restore items to parent if this was a subgroup."""
        if self._executed and self._group:
            # Delete the group (keep items)
            self._group_manager.delete_group(self._group.group_uuid, keep_items=True)

            # If this was a subgroup, restore items to parent group
            if self._parent_group_uuid:
                parent = self._group_manager.get_group(self._parent_group_uuid)
                if parent:
                    for item_uuid in self._item_uuids:
                        if item_uuid not in parent.item_uuids:
                            parent.item_uuids.append(item_uuid)
                        self._group_manager._item_to_group[item_uuid] = self._parent_group_uuid
                    self._group_manager.groupsChanged.emit()

            self._executed = False


class DeleteGroupCommand(Command):
    """Command to delete a group."""

    def __init__(
        self,
        group_manager: GroupManager,
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
        self._group_manager = group_manager
        self._group_uuid = group_uuid
        self._keep_items = keep_items

        # Store full group data for restoration
        group = group_manager.get_group(group_uuid)
        if group:
            self._group_data: dict[str, Any] | None = group.to_dict()
        else:
            self._group_data = None

        # If not keeping items, store the actual items for restoration
        self._items: list[QtWidgets.QGraphicsItem] = []
        if not keep_items and group:
            self._items = group_manager.get_group_items(group_uuid)

    def execute(self) -> None:
        """Delete the group (works for both initial execute and redo)."""
        if not self._group_data:
            return

        # Check if group exists (it should after undo recreated it)
        if self._group_manager.get_group(self._group_uuid):
            self._group_manager.delete_group(self._group_uuid, keep_items=self._keep_items)

    def undo(self) -> None:
        """Restore the group."""
        if not self._group_data:
            return

        from .layer_group import LayerGroup

        # Re-add items to scene if they were deleted
        if not self._keep_items and self._items and self._group_manager.scene:
            for item in self._items:
                self._group_manager.scene.addItem(item)

        # If this was a subgroup, remove items from parent first
        # (they were moved there during delete)
        parent_group_uuid = self._group_data.get("parent_group_uuid")
        item_uuids = self._group_data.get("item_uuids", [])
        if self._keep_items and parent_group_uuid:
            parent = self._group_manager.get_group(parent_group_uuid)
            if parent:
                for item_uuid in item_uuids:
                    if item_uuid in parent.item_uuids:
                        parent.item_uuids.remove(item_uuid)

        # Recreate the group
        group = LayerGroup.from_dict(self._group_data)
        self._group_manager.add_group(group)


class AddItemToGroupCommand(Command):
    """Command to add an item to a group."""

    def __init__(
        self,
        group_manager: GroupManager,
        item_uuid: str,
        group_uuid: str,
    ):
        """
        Initialize AddItemToGroupCommand.

        Args:
            group_manager: The group manager to use
            item_uuid: UUID of the item to add
            group_uuid: UUID of the group to add to
        """
        self._group_manager = group_manager
        self._item_uuid = item_uuid
        self._target_group_uuid = group_uuid
        self._executed = False

        # Store previous group membership (if any)
        prev_group = group_manager.get_item_group(item_uuid)
        self._previous_group_uuid: str | None = prev_group.group_uuid if prev_group else None

    def execute(self) -> None:
        """Add item to the group."""
        if not self._executed:
            self._group_manager.add_item_to_group(self._item_uuid, self._target_group_uuid)
            self._executed = True

    def undo(self) -> None:
        """Remove item from group (restore previous membership if any)."""
        if self._executed:
            self._group_manager.remove_item_from_group(self._item_uuid)
            if self._previous_group_uuid:
                self._group_manager.add_item_to_group(self._item_uuid, self._previous_group_uuid)
            self._executed = False


class RemoveItemFromGroupCommand(Command):
    """Command to remove an item from its group."""

    def __init__(
        self,
        group_manager: GroupManager,
        item_uuid: str,
    ):
        """
        Initialize RemoveItemFromGroupCommand.

        Args:
            group_manager: The group manager to use
            item_uuid: UUID of the item to remove from its group
        """
        self._group_manager = group_manager
        self._item_uuid = item_uuid
        self._executed = False

        # Store group membership for restoration
        group = group_manager.get_item_group(item_uuid)
        self._group_uuid: str | None = group.group_uuid if group else None

        # Store full group data in case it gets auto-deleted
        if group:
            self._group_data: dict[str, Any] | None = group.to_dict()
        else:
            self._group_data = None

    def execute(self) -> None:
        """Remove item from its group."""
        if not self._executed and self._group_uuid:
            self._group_manager.remove_item_from_group(self._item_uuid)
            self._executed = True

    def undo(self) -> None:
        """Restore item to its group (recreate group if auto-deleted)."""
        if self._executed and self._group_uuid:
            # Check if group still exists
            if not self._group_manager.get_group(self._group_uuid) and self._group_data:
                # Recreate the auto-deleted group
                from .layer_group import LayerGroup

                group = LayerGroup.from_dict(self._group_data)
                self._group_manager.add_group(group)

            # Add item back to group
            self._group_manager.add_item_to_group(self._item_uuid, self._group_uuid)
            self._executed = False


class ImportAsLayerCommand(Command):
    """Command to import an assembly file as a layer (group)."""

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        group_manager: GroupManager,
        items: list[QtWidgets.QGraphicsItem],
        parent_group_data: dict[str, Any],
        imported_groups_data: list[dict[str, Any]],
    ):
        """
        Initialize ImportAsLayerCommand.

        Args:
            scene: The graphics scene
            group_manager: The group manager
            items: List of imported items
            parent_group_data: Data for the parent group (as dict)
            imported_groups_data: List of imported group data dicts
        """
        self._scene = scene
        self._group_manager = group_manager
        self._items = items
        self._parent_group_data = parent_group_data
        self._imported_groups_data = imported_groups_data

    def execute(self) -> None:
        """Add items and groups to scene (for redo)."""
        from .layer_group import LayerGroup

        # Add items to scene
        for item in self._items:
            if item.scene() is None:
                self._scene.addItem(item)

        # Recreate parent group
        parent_group = LayerGroup.from_dict(self._parent_group_data)
        self._group_manager.add_group(parent_group)

        # Recreate imported groups
        for group_data in self._imported_groups_data:
            group = LayerGroup.from_dict(group_data)
            self._group_manager.add_group(group)

    def undo(self) -> None:
        """Remove imported items and groups."""
        # Remove imported groups (in reverse order to handle hierarchy)
        for group_data in reversed(self._imported_groups_data):
            group_uuid = group_data.get("group_uuid")
            if group_uuid and self._group_manager.get_group(group_uuid):
                self._group_manager.delete_group(group_uuid, keep_items=True)

        # Remove parent group
        parent_uuid = self._parent_group_data.get("group_uuid")
        if parent_uuid and self._group_manager.get_group(parent_uuid):
            self._group_manager.delete_group(parent_uuid, keep_items=True)

        # Remove items from scene
        for item in self._items:
            if item.scene() is not None:
                self._scene.removeItem(item)


# --- Layer Tree Model Commands (new architecture) ---


class MoveLayerCommand(Command):
    """Command to move an item/group to a new position in the layer tree."""

    def __init__(
        self,
        model: Any,  # LayerTreeModel
        uuid: str,
        old_parent: str | None,
        old_index: int,
        new_parent: str | None,
        new_index: int,
    ):
        """
        Initialize MoveLayerCommand.

        Args:
            model: The LayerTreeModel
            uuid: UUID of item/group to move
            old_parent: Old parent group UUID (None for root)
            old_index: Old index within parent
            new_parent: New parent group UUID (None for root)
            new_index: New index within new parent
        """
        self._model = model
        self._uuid = uuid
        self._old_parent = old_parent
        self._old_index = old_index
        self._new_parent = new_parent
        self._new_index = new_index

    def execute(self) -> None:
        """Move to new position."""
        self._model.move_item(self._uuid, self._new_parent, self._new_index)

    def undo(self) -> None:
        """Move back to old position."""
        self._model.move_item(self._uuid, self._old_parent, self._old_index)


class AddLayerItemCommand(Command):
    """Command to add an item to the layer model."""

    def __init__(
        self,
        model: Any,  # LayerTreeModel
        uuid: str,
        parent_group: str | None = None,
        index: int = 0,
    ):
        """
        Initialize AddLayerItemCommand.

        Args:
            model: The LayerTreeModel
            uuid: Item UUID to add
            parent_group: Parent group UUID (None for root)
            index: Position within parent
        """
        self._model = model
        self._uuid = uuid
        self._parent_group = parent_group
        self._index = index

    def execute(self) -> None:
        """Add item to model."""
        self._model.add_item(self._uuid, self._parent_group, self._index)

    def undo(self) -> None:
        """Remove item from model."""
        self._model.remove_item(self._uuid)


class RemoveLayerItemCommand(Command):
    """Command to remove an item from the layer model."""

    def __init__(
        self,
        model: Any,  # LayerTreeModel
        uuid: str,
    ):
        """
        Initialize RemoveLayerItemCommand.

        Args:
            model: The LayerTreeModel
            uuid: Item UUID to remove
        """
        self._model = model
        self._uuid = uuid
        self._old_parent: str | None = None
        self._old_index: int = 0

        # Store current position for undo
        node = model.get_node(uuid)
        if node:
            if node.parent:
                self._old_parent = node.parent.uuid
                self._old_index = node.parent.children.index(node)
            else:
                self._old_index = model.get_root_nodes().index(node) if node in model.get_root_nodes() else 0

    def execute(self) -> None:
        """Remove item from model."""
        self._model.remove_item(self._uuid)

    def undo(self) -> None:
        """Restore item to model."""
        self._model.add_item(self._uuid, self._old_parent, self._old_index)


class CreateLayerGroupCommand(Command):
    """Command to create a group in the layer model."""

    def __init__(
        self,
        model: Any,  # LayerTreeModel
        name: str,
        item_uuids: list[str],
        parent_group: str | None = None,
    ):
        """
        Initialize CreateLayerGroupCommand.

        Args:
            model: The LayerTreeModel
            name: Group name
            item_uuids: UUIDs of items to include
            parent_group: Parent group UUID (None for root)
        """
        self._model = model
        self._name = name
        self._item_uuids = list(item_uuids)
        self._parent_group = parent_group
        self._group_uuid: str | None = None

        # Store original positions for undo
        self._original_positions: list[tuple[str | None, int]] = []
        for uuid in item_uuids:
            node = model.get_node(uuid)
            if node:
                if node.parent:
                    self._original_positions.append((node.parent.uuid, node.parent.children.index(node)))
                else:
                    roots = model.get_root_nodes()
                    self._original_positions.append((None, roots.index(node) if node in roots else 0))

    def execute(self) -> None:
        """Create the group."""
        self._group_uuid = self._model.create_group(self._name, self._item_uuids, self._parent_group)

    def undo(self) -> None:
        """Delete the group and restore items to original positions."""
        if self._group_uuid:
            self._model.delete_group(self._group_uuid, emit=False)

            # Restore items to original positions
            for i, uuid in enumerate(self._item_uuids):
                if i < len(self._original_positions):
                    parent, index = self._original_positions[i]
                    self._model.move_item(uuid, parent, index, emit=False)

            self._model.structureChanged.emit()


class DeleteLayerGroupCommand(Command):
    """Command to delete a group from the layer model."""

    def __init__(
        self,
        model: Any,  # LayerTreeModel
        group_uuid: str,
    ):
        """
        Initialize DeleteLayerGroupCommand.

        Args:
            model: The LayerTreeModel
            group_uuid: Group UUID to delete
        """
        self._model = model
        self._group_uuid = group_uuid

        # Store group info for undo
        node = model.get_node(group_uuid)
        if node and node.is_group():
            self._name = node.name or ""
            self._collapsed = node.collapsed
            self._item_uuids = [child.uuid for child in node.children if child.is_item()]
            self._parent: str | None = node.parent.uuid if node.parent else None
            roots = model.get_root_nodes()
            self._index = roots.index(node) if node in roots else 0
        else:
            self._name = ""
            self._collapsed = False
            self._item_uuids = []
            self._parent = None
            self._index = 0

    def execute(self) -> None:
        """Delete the group."""
        self._model.delete_group(self._group_uuid)

    def undo(self) -> None:
        """Recreate the group."""
        new_uuid = self._model.create_group(self._name, self._item_uuids, self._parent, emit=False)
        if new_uuid:
            # Note: UUID will be different, but structure is restored
            node = self._model.get_node(new_uuid)
            if node:
                node.collapsed = self._collapsed
        self._model.structureChanged.emit()


class RenameLayerGroupCommand(Command):
    """Command to rename a group in the layer model."""

    def __init__(
        self,
        model: Any,  # LayerTreeModel
        group_uuid: str,
        new_name: str,
    ):
        """
        Initialize RenameLayerGroupCommand.

        Args:
            model: The LayerTreeModel
            group_uuid: Group UUID to rename
            new_name: New name for the group
        """
        self._model = model
        self._group_uuid = group_uuid
        self._new_name = new_name

        # Store old name for undo
        node = model.get_node(group_uuid)
        self._old_name = node.name if node else ""

    def execute(self) -> None:
        """Rename the group."""
        self._model.rename_group(self._group_uuid, self._new_name)

    def undo(self) -> None:
        """Restore old name."""
        self._model.rename_group(self._group_uuid, self._old_name or "")


class AddToLayerGroupCommand(Command):
    """Command to add an item to a group in the layer model."""

    def __init__(
        self,
        model: Any,  # LayerTreeModel
        item_uuid: str,
        group_uuid: str,
        index: int | None = None,
    ):
        """
        Initialize AddToLayerGroupCommand.

        Args:
            model: The LayerTreeModel
            item_uuid: Item UUID to add
            group_uuid: Group UUID to add to
            index: Position in group (None for end)
        """
        self._model = model
        self._item_uuid = item_uuid
        self._group_uuid = group_uuid
        self._index = index

        # Store original position for undo
        node = model.get_node(item_uuid)
        if node:
            if node.parent:
                self._old_parent: str | None = node.parent.uuid
                self._old_index = node.parent.children.index(node)
            else:
                self._old_parent = None
                roots = model.get_root_nodes()
                self._old_index = roots.index(node) if node in roots else 0
        else:
            self._old_parent = None
            self._old_index = 0

    def execute(self) -> None:
        """Add item to group."""
        self._model.add_item_to_group(self._item_uuid, self._group_uuid, self._index)

    def undo(self) -> None:
        """Restore item to original position."""
        self._model.move_item(self._item_uuid, self._old_parent, self._old_index)


class RemoveFromLayerGroupCommand(Command):
    """Command to remove an item from its group in the layer model."""

    def __init__(
        self,
        model: Any,  # LayerTreeModel
        item_uuid: str,
    ):
        """
        Initialize RemoveFromLayerGroupCommand.

        Args:
            model: The LayerTreeModel
            item_uuid: Item UUID to remove from its group
        """
        self._model = model
        self._item_uuid = item_uuid

        # Store group info for undo
        node = model.get_node(item_uuid)
        if node and node.parent and node.parent.is_group():
            self._group_uuid: str | None = node.parent.uuid
            self._index = node.parent.children.index(node)
        else:
            self._group_uuid = None
            self._index = 0

    def execute(self) -> None:
        """Remove item from group."""
        self._model.remove_item_from_group(self._item_uuid)

    def undo(self) -> None:
        """Restore item to group."""
        if self._group_uuid:
            self._model.add_item_to_group(self._item_uuid, self._group_uuid, self._index)
