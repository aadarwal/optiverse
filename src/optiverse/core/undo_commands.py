"""
Command pattern implementation for undo/redo functionality.
Each command encapsulates an action that can be executed and undone.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
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
        parent_uuid: str | None = None,
    ):
        """
        Initialize AddItemCommand.

        Args:
            scene: The graphics scene to add the item to
            item: The graphics item to add
            parent_uuid: Optional parent node UUID (group or item) for layer nesting
        """
        self.scene = scene
        self.item = item
        self._layer_state = layer_state
        self._parent_uuid = parent_uuid
        self._executed = False

    def execute(self) -> None:
        """Add the item to the scene."""
        if not self._executed:
            self.scene.addItem(self.item)
            if self._layer_state and hasattr(self.item, "item_uuid"):
                self._layer_state.add_item(
                    str(self.item.item_uuid), self._parent_uuid, 0, emit=True
                )
            self._executed = True

    def undo(self) -> None:
        """Remove the item from the scene."""
        if self._executed:
            if self._layer_state and hasattr(self.item, "item_uuid"):
                self._layer_state.remove_item(str(self.item.item_uuid), emit=True)
            self.scene.removeItem(self.item)
            self._executed = False


def _collect_empty_ancestor_groups(
    layer_state: LayerTreeState,
    parent_uuids: set[str],
) -> list[tuple[dict[str, Any], str | None, int]]:
    """Walk up from parent groups and collect snapshots of empty non-linked groups.

    Returns a list of (snapshot_dict, parent_uuid, index) tuples in leaf-to-root
    order (i.e. innermost empty group first). Each group is removed from the tree
    as it is collected so that its own parent can then be checked for emptiness.
    """
    from .layer_tree_state import LayerNode

    def _node_to_dict(n: LayerNode) -> dict[str, Any]:
        d: dict[str, Any] = {"uuid": n.uuid, "type": n.node_type}
        if n.name is not None:
            d["name"] = n.name
        if n.collapsed:
            d["collapsed"] = True
        if not n.visible:
            d["visible"] = False
        if n.locked:
            d["locked"] = True
        if n.link_metadata is not None:
            d["link_metadata"] = n.link_metadata.to_dict()
        return d

    removed: list[tuple[dict[str, Any], str | None, int]] = []
    visited: set[str] = set()

    for group_uuid in parent_uuids:
        current_uuid: str | None = group_uuid
        while current_uuid and current_uuid not in visited:
            visited.add(current_uuid)
            node = layer_state.get_node(current_uuid)
            if not node or not node.is_group():
                break
            if node.is_linked():
                break
            if node.children:
                break
            # Empty non-linked group — snapshot and remove
            parent_node = node.parent
            parent_uid = parent_node.uuid if parent_node else None
            siblings = parent_node.children if parent_node else layer_state.get_root_nodes()
            try:
                idx = siblings.index(node)
            except ValueError:
                idx = 0
            snapshot = _node_to_dict(node)
            removed.append((snapshot, parent_uid, idx))
            layer_state.delete_group(current_uuid, emit=False)
            current_uuid = parent_uid

    return removed


def _restore_empty_ancestor_groups(
    layer_state: LayerTreeState,
    removed_groups: list[tuple[dict[str, Any], str | None, int]],
) -> None:
    """Recreate previously auto-deleted empty groups (in reverse order = root-first)."""
    from .layer_tree_state import LinkMetadata

    for snapshot, parent_uuid, idx in reversed(removed_groups):
        gid = snapshot["uuid"]
        if layer_state.get_node(gid):
            continue
        lm_data = snapshot.get("link_metadata")
        if lm_data:
            layer_state.create_linked_group(
                snapshot.get("name") or "Group",
                link_metadata=LinkMetadata.from_dict(lm_data),
                parent_group_uuid=parent_uuid,
                index=idx,
                group_uuid=gid,
                emit=False,
            )
        else:
            layer_state.create_group(
                snapshot.get("name") or "Group",
                parent_group_uuid=parent_uuid,
                index=idx,
                group_uuid=gid,
                emit=False,
            )
        node = layer_state.get_node(gid)
        if node:
            node.collapsed = bool(snapshot.get("collapsed", False))
            node.visible = snapshot.get("visible", True)
            node.locked = bool(snapshot.get("locked", False))


def _find_autolabels(
    scene: QtWidgets.QGraphicsScene,
    owner_uuid: str,
) -> list:
    """Return all TextNoteItem autolabels in *scene* owned by *owner_uuid*."""
    from ..objects.annotations.text_note_item import TextNoteItem

    return [
        it
        for it in scene.items()
        if isinstance(it, TextNoteItem) and it.owner_uuid == owner_uuid
    ]


def _disconnect_autolabel(owner, label) -> None:
    """Safely disconnect the owner's edited signal from the label."""
    try:
        owner.edited.disconnect(label.follow_owner)
    except (TypeError, RuntimeError, AttributeError):
        pass


def _reconnect_autolabel(owner, label) -> None:
    """Re-connect the owner's edited signal to the label."""
    if hasattr(owner, "edited"):
        owner.edited.connect(label.follow_owner)


class RemoveItemCommand(Command):
    """Command to remove an item from the scene.

    When the item owns autolabels (TextNoteItems with matching ``owner_uuid``),
    those labels are cascade-removed together and restored on undo.
    """

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        item: QtWidgets.QGraphicsItem,
        layer_state: LayerTreeState | None = None,
    ):
        self.scene = scene
        self.item = item
        self._layer_state = layer_state
        self._executed = False
        self._removed_groups: list[tuple[dict[str, Any], str | None, int]] = []

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

        # If the item IS an autolabel, store a reference to its owner so we
        # can disconnect/reconnect the edited signal on execute/undo.
        self._autolabel_owner: Any | None = None
        owner_uuid = getattr(item, "owner_uuid", None)
        if owner_uuid:
            for it in scene.items():
                if getattr(it, "item_uuid", None) == owner_uuid:
                    self._autolabel_owner = it
                    break

        # Cascade: collect autolabels owned by this item
        self._cascade_labels: list = []
        self._cascade_placements: dict[str, tuple[str | None, int]] = {}
        if self._item_uuid:
            self._cascade_labels = _find_autolabels(scene, self._item_uuid)
            if self._layer_state:
                for lbl in self._cascade_labels:
                    lbl_uuid = getattr(lbl, "item_uuid", None)
                    if not lbl_uuid:
                        continue
                    node = self._layer_state.get_node(lbl_uuid)
                    if node:
                        if node.parent:
                            self._cascade_placements[lbl_uuid] = (
                                node.parent.uuid,
                                node.parent.children.index(node),
                            )
                        else:
                            roots = self._layer_state.get_root_nodes()
                            self._cascade_placements[lbl_uuid] = (
                                None,
                                roots.index(node) if node in roots else 0,
                            )

    def execute(self) -> None:
        """Remove the item from the scene and its group."""
        if not self._executed:
            # Disconnect autolabel from its owner (when deleting the label itself)
            if self._autolabel_owner is not None:
                _disconnect_autolabel(self._autolabel_owner, self.item)

            # Disconnect and remove cascade autolabels first
            for lbl in self._cascade_labels:
                _disconnect_autolabel(self.item, lbl)
                lbl_uuid = getattr(lbl, "item_uuid", None)
                if self._layer_state and lbl_uuid:
                    self._layer_state.remove_item(lbl_uuid, emit=False)
                self.scene.removeItem(lbl)

            if self._layer_state and self._item_uuid:
                self._layer_state.remove_item(self._item_uuid, emit=False)
                # Auto-delete empty ancestor groups
                parent_uuids = {self._old_parent_uuid} if self._old_parent_uuid else set()
                parent_uuids |= {
                    p for p, _ in self._cascade_placements.values() if p is not None
                }
                if parent_uuids:
                    self._removed_groups = _collect_empty_ancestor_groups(
                        self._layer_state, parent_uuids
                    )
                self._layer_state.changed.emit()
            self.scene.removeItem(self.item)
            self._executed = True

    def undo(self) -> None:
        """Add the item back to the scene and restore group membership."""
        if self._executed:
            self.scene.addItem(self.item)
            if self._layer_state and self._item_uuid:
                # Restore auto-deleted groups first so parent exists
                if self._removed_groups:
                    _restore_empty_ancestor_groups(self._layer_state, self._removed_groups)
                    self._removed_groups = []
                # Restore item placement
                if self._old_parent_uuid and self._layer_state.get_node(self._old_parent_uuid):
                    self._layer_state.add_item(
                        self._item_uuid, self._old_parent_uuid, self._old_index, emit=True
                    )
                else:
                    self._layer_state.add_item(self._item_uuid, None, self._old_index, emit=True)

            # Reconnect autolabel to its owner (when undoing label deletion)
            if self._autolabel_owner is not None:
                _reconnect_autolabel(self._autolabel_owner, self.item)

            # Restore cascade autolabels
            for lbl in self._cascade_labels:
                self.scene.addItem(lbl)
                _reconnect_autolabel(self.item, lbl)
                lbl_uuid = getattr(lbl, "item_uuid", None)
                if self._layer_state and lbl_uuid:
                    parent_uuid, idx = self._cascade_placements.get(lbl_uuid, (None, 0))
                    self._layer_state.add_item(lbl_uuid, parent_uuid, idx, emit=False)
            if self._layer_state and self._cascade_labels:
                self._layer_state.changed.emit()

            self._executed = False


class MoveItemCommand(Command):
    """Command to move an item to a new position.

    Consecutive moves within MERGE_WINDOW_S of the same item merge into
    one undo step (i.e., a single drag). A new drag after the window
    expires creates a separate undo step.
    """

    MERGE_WINDOW_S = 0.5  # seconds — moves further apart are separate undo steps

    def __init__(
        self,
        item: QtWidgets.QGraphicsItem,
        old_pos: QtCore.QPointF,
        new_pos: QtCore.QPointF,
    ):
        self.item = item
        self.old_pos = QtCore.QPointF(old_pos)
        self.new_pos = QtCore.QPointF(new_pos)
        self._timestamp = time.monotonic()

    def execute(self) -> None:
        self.item.setPos(self.new_pos)
        self.item.setTransform(self.item.transform())
        if hasattr(self.item, "edited"):
            self.item.edited.emit()

    def undo(self) -> None:
        self.item.setPos(self.old_pos)
        self.item.setTransform(self.item.transform())
        if hasattr(self.item, "edited"):
            self.item.edited.emit()

    def id(self) -> int:
        return id(self.item)

    def merge_with(self, other: Command) -> bool:
        if not isinstance(other, MoveItemCommand):
            return False
        if other.item is not self.item:
            return False
        # Only merge if the new command arrived within the merge window
        if other._timestamp - self._timestamp > self.MERGE_WINDOW_S:
            return False
        self.new_pos = QtCore.QPointF(other.new_pos)
        self._timestamp = other._timestamp
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
    """Command to remove multiple items from the scene in a single operation.

    Autolabels owned by any of the removed items are cascade-removed and
    restored on undo, analogous to ``RemoveItemCommand``.
    """

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        items: list[QtWidgets.QGraphicsItem],
        layer_state: LayerTreeState | None = None,
    ):
        self.scene = scene
        self.items = items
        self._layer_state = layer_state
        self._executed = False
        self._removed_groups: list[tuple[dict[str, Any], str | None, int]] = []

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
                        self._placements[item_uuid] = (
                            node.parent.uuid,
                            node.parent.children.index(node),
                        )
                    else:
                        roots = self._layer_state.get_root_nodes()
                        self._placements[item_uuid] = (
                            None,
                            roots.index(node) if node in roots else 0,
                        )

        # Cascade: collect autolabels owned by any of the items being removed
        item_uuids = {
            getattr(it, "item_uuid", None) for it in items
        } - {None}
        self._cascade_labels: list = []
        self._cascade_owners: dict[str, Any] = {}  # label uuid -> owner item
        self._cascade_placements: dict[str, tuple[str | None, int]] = {}

        # Track items that ARE autolabels so we can disconnect from their owners
        self._autolabel_owners: dict[str, Any] = {}  # item uuid -> owner item
        for it in items:
            owner_uuid = getattr(it, "owner_uuid", None)
            if owner_uuid and owner_uuid not in item_uuids:
                for scene_it in scene.items():
                    if getattr(scene_it, "item_uuid", None) == owner_uuid:
                        self._autolabel_owners[it.item_uuid] = scene_it
                        break

        for uid in item_uuids:
            labels = _find_autolabels(scene, uid)  # type: ignore[arg-type]
            # Skip labels that are already in the explicit items list
            labels = [
                lbl for lbl in labels
                if getattr(lbl, "item_uuid", None) not in item_uuids
            ]
            owner = next((it for it in items if getattr(it, "item_uuid", None) == uid), None)
            for lbl in labels:
                self._cascade_labels.append(lbl)
                self._cascade_owners[lbl.item_uuid] = owner
                if self._layer_state:
                    lbl_uuid = lbl.item_uuid
                    node = self._layer_state.get_node(lbl_uuid)
                    if node:
                        if node.parent:
                            self._cascade_placements[lbl_uuid] = (
                                node.parent.uuid,
                                node.parent.children.index(node),
                            )
                        else:
                            roots = self._layer_state.get_root_nodes()
                            self._cascade_placements[lbl_uuid] = (
                                None,
                                roots.index(node) if node in roots else 0,
                            )

    def execute(self) -> None:
        """Remove all items from the scene and their groups."""
        if not self._executed:
            # Disconnect items that are autolabels from their owners
            for item_uuid, owner in self._autolabel_owners.items():
                label = next(
                    (it for it in self.items if getattr(it, "item_uuid", None) == item_uuid),
                    None,
                )
                if label is not None:
                    _disconnect_autolabel(owner, label)

            # Cascade: disconnect and remove autolabels first
            for lbl in self._cascade_labels:
                owner = self._cascade_owners.get(lbl.item_uuid)
                if owner is not None:
                    _disconnect_autolabel(owner, lbl)
                lbl_uuid = getattr(lbl, "item_uuid", None)
                if self._layer_state and lbl_uuid:
                    self._layer_state.remove_item(lbl_uuid, emit=False)
                self.scene.removeItem(lbl)

            if self._layer_state:
                for item in self.items:
                    item_uuid = getattr(item, "item_uuid", None)
                    if item_uuid:
                        self._layer_state.remove_item(item_uuid, emit=False)
                # Auto-delete empty ancestor groups
                parent_uuids = {
                    p for p, _ in self._placements.values() if p is not None
                }
                parent_uuids |= {
                    p for p, _ in self._cascade_placements.values() if p is not None
                }
                if parent_uuids:
                    self._removed_groups = _collect_empty_ancestor_groups(
                        self._layer_state, parent_uuids
                    )
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
                # Restore auto-deleted groups first so parents exist
                if self._removed_groups:
                    _restore_empty_ancestor_groups(self._layer_state, self._removed_groups)
                    self._removed_groups = []
                for item in self.items:
                    item_uuid = getattr(item, "item_uuid", None)
                    if not item_uuid:
                        continue
                    parent_uuid, idx = self._placements.get(item_uuid, (None, 0))
                    self._layer_state.add_item(item_uuid, parent_uuid, idx, emit=False)
                self._layer_state.changed.emit()

            # Reconnect items that are autolabels to their owners
            for item_uuid, owner in self._autolabel_owners.items():
                label = next(
                    (it for it in self.items if getattr(it, "item_uuid", None) == item_uuid),
                    None,
                )
                if label is not None:
                    _reconnect_autolabel(owner, label)

            # Restore cascade autolabels
            for lbl in self._cascade_labels:
                self.scene.addItem(lbl)
                owner = self._cascade_owners.get(lbl.item_uuid)
                if owner is not None:
                    _reconnect_autolabel(owner, lbl)
                lbl_uuid = getattr(lbl, "item_uuid", None)
                if self._layer_state and lbl_uuid:
                    parent_uuid, idx = self._cascade_placements.get(lbl_uuid, (None, 0))
                    self._layer_state.add_item(lbl_uuid, parent_uuid, idx, emit=False)
            if self._layer_state and self._cascade_labels:
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
        if hasattr(self.item, "edited"):
            self.item.edited.emit()

    def undo(self) -> None:
        """Rotate the item back to the old angle."""
        self.item.setRotation(self.old_rotation)
        if hasattr(self.item, "edited"):
            self.item.edited.emit()


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
            if hasattr(item, "edited"):
                item.edited.emit()

    def undo(self) -> None:
        """Restore old positions and rotations for all items."""
        for item in self.items:
            item.setPos(self.old_positions[item])
            item.setRotation(self.old_rotations[item])
            if hasattr(item, "edited"):
                item.edited.emit()


class BatchCommand(Command):
    """Execute multiple Commands as one undo/redo step."""

    def __init__(self, commands: Sequence[Command]):
        self._commands = [c for c in commands if c is not None]

    def execute(self) -> None:
        for cmd in self._commands:
            cmd.execute()

    def undo(self) -> None:
        for cmd in reversed(self._commands):
            cmd.undo()


class UpdateLinkOffsetCommand(Command):
    """Update a linked assembly's offset in its metadata (undoable)."""

    def __init__(
        self,
        layer_state: LayerTreeState,
        link_uuid: str,
        old_offset: tuple[float, float],
        new_offset: tuple[float, float],
    ):
        self._layer_state = layer_state
        self._link_uuid = link_uuid
        self._old_offset = old_offset
        self._new_offset = new_offset

    def execute(self) -> None:
        self._apply_offset(self._new_offset)

    def undo(self) -> None:
        self._apply_offset(self._old_offset)

    def _apply_offset(self, offset: tuple[float, float]) -> None:
        node = self._layer_state.get_node(self._link_uuid)
        if node and node.link_metadata:
            node.link_metadata.offset_x = offset[0]
            node.link_metadata.offset_y = offset[1]


class BatchPropertyChangeCommand(Command):
    """Undo/redo batch property changes across multiple items.

    Stores a list of (item, old_state, new_state) triples so that
    capture_state/apply_state on each item drives the undo/redo cycle.
    """

    def __init__(
        self,
        entries: list[tuple[Undoable, dict[str, Any], dict[str, Any]]],
    ):
        self._entries = entries

    def execute(self) -> None:
        for item, _old, new in self._entries:
            item.apply_state(new)

    def undo(self) -> None:
        for item, old, _new in self._entries:
            item.apply_state(old)


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
        # Insert group where the first item currently sits within the target parent
        # (when applicable)
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
            def node_to_dict(n):
                d = {"uuid": n.uuid, "type": n.node_type}
                if n.name is not None:
                    d["name"] = n.name
                if n.collapsed:
                    d["collapsed"] = True
                if not n.visible:
                    d["visible"] = False
                if n.locked:
                    d["locked"] = True
                if n.link_metadata is not None:
                    d["link_metadata"] = n.link_metadata.to_dict()
                if n.children:
                    d["children"] = [node_to_dict(c) for c in n.children]
                return d
            self._snapshot = node_to_dict(node)

    def execute(self) -> None:
        """Delete the group (works for both initial execute and redo).

        When keep_items=False, the caller is responsible for removing child
        items from the scene via separate RemoveItemCommand(s).
        """
        if not self._snapshot:
            return
        if self._layer_state.get_node(self._group_uuid):
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
        # Add group node (UUID preserved), restoring link_metadata if present
        lm_data = self._snapshot.get("link_metadata")
        if lm_data:
            from .layer_tree_state import LinkMetadata

            self._layer_state.create_linked_group(
                root.name or "Group",
                link_metadata=LinkMetadata.from_dict(lm_data),
                parent_group_uuid=self._old_parent_uuid,
                index=self._old_index,
                group_uuid=root.uuid,
                emit=False,
            )
        else:
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
                    ch_lm = ch.get("link_metadata")
                    if ch_lm:
                        from .layer_tree_state import LinkMetadata

                        self._layer_state.create_linked_group(
                            ch.get("name", "Group"),
                            link_metadata=LinkMetadata.from_dict(ch_lm),
                            parent_group_uuid=parent_uuid,
                            group_uuid=gid,
                            emit=False,
                        )
                    else:
                        self._layer_state.create_group(
                            ch.get("name", "Group"),
                            parent_group_uuid=parent_uuid,
                            group_uuid=gid,
                            emit=False,
                        )
                    self._layer_state.set_group_collapsed(
                        gid, bool(ch.get("collapsed", False)), emit=False
                    )
                    gnode = self._layer_state.get_node(gid)
                    if gnode:
                        gnode.visible = ch.get("visible", True)
                        gnode.locked = ch.get("locked", False)
                    add_children(gid, ch.get("children", []) or [])
                else:
                    self._layer_state.add_item(ch["uuid"], parent_uuid, index=10**9, emit=False)
                    inode = self._layer_state.get_node(ch["uuid"])
                    if inode:
                        inode.visible = ch.get("visible", True)
                        inode.locked = ch.get("locked", False)
        add_children(root.uuid, self._snapshot.get("children", []) or [])
        rnode = self._layer_state.get_node(root.uuid)
        if rnode:
            rnode.visible = self._snapshot.get("visible", True)
            rnode.locked = self._snapshot.get("locked", False)
        self._layer_state.changed.emit()


# =============================================================================
# Layer Panel Commands (rename, visibility, lock, z-order)
# =============================================================================


class RenameNodeCommand(Command):
    """Undoable rename of a group or item in the layer panel."""

    def __init__(
        self,
        layer_state: LayerTreeState,
        uuid: str,
        old_name: str | None,
        new_name: str | None,
        *,
        is_group: bool = False,
        item: QtWidgets.QGraphicsItem | None = None,
    ):
        self._layer_state = layer_state
        self._uuid = uuid
        self._old_name = old_name
        self._new_name = new_name
        self._is_group = is_group
        self._item = item

    def execute(self) -> None:
        self._apply(self._new_name)

    def undo(self) -> None:
        self._apply(self._old_name)

    def _apply(self, name: str | None) -> None:
        if self._is_group:
            self._layer_state.rename_group(self._uuid, name or "Group", emit=True)
        elif self._item is not None:
            if hasattr(self._item, "display_name"):
                self._item.display_name = name if name else None
            elif hasattr(self._item, "params") and hasattr(self._item.params, "name"):
                self._item.params.name = name if name else None


class ToggleVisibilityCommand(Command):
    """Undoable visibility toggle for a layer node."""

    def __init__(self, node, old_visible: bool, new_visible: bool, apply_fn):
        self._node = node
        self._old = old_visible
        self._new = new_visible
        self._apply_fn = apply_fn

    def execute(self) -> None:
        self._node.visible = self._new
        self._apply_fn(self._node)

    def undo(self) -> None:
        self._node.visible = self._old
        self._apply_fn(self._node)


class ToggleLockCommand(Command):
    """Undoable lock toggle for a layer node."""

    def __init__(self, node, old_locked: bool, new_locked: bool, apply_fn):
        self._node = node
        self._old = old_locked
        self._new = new_locked
        self._apply_fn = apply_fn

    def execute(self) -> None:
        self._node.locked = self._new
        self._apply_fn(self._node)

    def undo(self) -> None:
        self._node.locked = self._old
        self._apply_fn(self._node)


class ZOrderCommand(Command):
    """Undoable z-order operation on layer tree nodes."""

    def __init__(
        self,
        layer_state: LayerTreeState,
        uuids: list[str],
        operation: str,
    ):
        self._layer_state = layer_state
        self._uuids = list(uuids)
        self._operation = operation
        # Snapshot all affected parents' children lists before the operation
        self._before_snapshot: dict[str | None, list[str]] = {}
        self._snapshot_parents(self._before_snapshot)
        self._after_snapshot: dict[str | None, list[str]] = {}

    def _snapshot_parents(self, target: dict[str | None, list[str]]) -> None:
        """Record children UUID lists for every parent that contains an affected node."""
        seen: set[str | None] = set()
        for uid in self._uuids:
            node = self._layer_state.get_node(uid)
            if not node:
                continue
            parent_uuid = node.parent.uuid if node.parent else None
            if parent_uuid in seen:
                continue
            seen.add(parent_uuid)
            siblings = node.parent.children if node.parent else self._layer_state.get_root_nodes()
            target[parent_uuid] = [ch.uuid for ch in siblings]

    def execute(self) -> None:
        self._layer_state.apply_z_order_operation(self._uuids, self._operation)
        if not self._after_snapshot:
            self._snapshot_parents(self._after_snapshot)

    def undo(self) -> None:
        self._restore_order(self._before_snapshot)

    def _restore_order(self, snapshot: dict[str | None, list[str]]) -> None:
        self._layer_state.begin_update()
        try:
            for parent_uuid, child_uuids in snapshot.items():
                for i, uid in enumerate(child_uuids):
                    self._layer_state.move_node(uid, parent_uuid, i, emit=False)
        finally:
            self._layer_state.end_update()


class TextEditCommand(Command):
    """Undoable inline text edit for TextNoteItem."""

    def __init__(self, item, old_text: str, new_text: str):
        self._item = item
        self._old_text = old_text
        self._new_text = new_text

    def execute(self) -> None:
        self._item.setPlainText(self._new_text)

    def undo(self) -> None:
        self._item.setPlainText(self._old_text)


class RectangleChangeCommand(Command):
    """Undoable property change for RectangleItem (pos, rotation, size)."""

    def __init__(self, item, before: dict[str, Any], after: dict[str, Any]):
        self._item = item
        self._before = before
        self._after = after

    def execute(self) -> None:
        self._apply(self._after)

    def undo(self) -> None:
        self._apply(self._before)

    def _apply(self, state: dict[str, Any]) -> None:
        self._item.setPos(state["x"], state["y"])
        self._item.setRotation(state["rotation"])
        self._item.prepareGeometryChange()
        self._item._w = state["width"]
        self._item._h = state["height"]
        self._item.update()
