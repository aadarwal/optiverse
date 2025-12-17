"""Qt item model backing the Layer panel (tree + drag/drop) without setItemWidget().

This model is designed to replace the previous QTreeWidget + setItemWidget approach
which is fragile during InternalMove drag/drop (widgets get orphaned/discarded).

It integrates with the application state:
- Scene items (QGraphicsItem) are the source for visibility/lock state.
- Layer hierarchy + order come from LayerTreeState (single source of truth).
- Scene z-values are derived output (applied elsewhere by LayerZOrderApplier).

Undo/redo integration is handled by pushing Commands to UndoStack when available.
"""

from __future__ import annotations

import sys
import traceback
import faulthandler

# Enable faulthandler to get stack traces on segfault
faulthandler.enable()

from typing import TYPE_CHECKING, Iterable

from PyQt6 import QtCore, QtGui, QtWidgets

# Debug flag - set to True for verbose logging
_DEBUG_MODEL = True

def _dbg(msg: str) -> None:
    if _DEBUG_MODEL:
        print(f"[LayerItemModel] {msg}", flush=True)

from ...core.undo_commands import BatchCommand, Command, MoveNodeCommand
from ...core.layer_tree_state import LayerTreeState, LayerNode

if TYPE_CHECKING:
    from ...core.undo_stack import UndoStack


# Data roles (kept compatible with old `layer_panel.py` constants)
ITEM_UUID_ROLE = QtCore.Qt.ItemDataRole.UserRole
GROUP_UUID_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
IS_GROUP_ROLE = QtCore.Qt.ItemDataRole.UserRole + 2

# Additional roles for delegate / interactions
VISIBLE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 10
LOCKED_ROLE = QtCore.Qt.ItemDataRole.UserRole + 11


MIME_TYPE_LAYER_ITEMS = "application/x-optiverse-layer-item-uuids"


class LayerItemModel(QtCore.QAbstractItemModel):
    """Tree model for layers (groups + items) with internal drag-drop and toggle actions."""

    orderChanged = QtCore.pyqtSignal()

    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._scene: QtWidgets.QGraphicsScene | None = None
        self._layer_state: LayerTreeState | None = None
        self._undo_stack: UndoStack | None = None
        self._uuid_to_item: dict[str, QtWidgets.QGraphicsItem] = {}

        self._order: list[str] = []  # global item order (top to bottom)
        
        # Persistent storage for internal pointer data to prevent GC issues.
        # Qt's createIndex() stores a raw pointer to Python objects; if those
        # objects are temporary (like tuple literals), they can be garbage-collected
        # while Qt still holds a pointer, causing segfaults.
        self._index_data: dict[str, tuple[str, int]] = {}

    # --- Public setup ---

    def set_context(
        self,
        *,
        scene: QtWidgets.QGraphicsScene | None,
        layer_state: LayerTreeState | None,
        undo_stack: UndoStack | None,
    ) -> None:
        self._scene = scene
        self._layer_state = layer_state
        self._undo_stack = undo_stack
        self.refresh()

    def refresh(self) -> None:
        """Refresh the model from authoritative LayerTreeState + current scene cache."""
        _dbg("refresh() START - calling beginResetModel")
        self.beginResetModel()
        try:
            # Clear persistent index data on reset to avoid stale pointers
            old_count = len(self._index_data)
            self._index_data.clear()
            _dbg(f"refresh() cleared {old_count} index_data entries")
            self._rebuild_caches()
            # Ordering is defined by the authoritative state.
            self._order = self._layer_state.get_all_items_in_order() if self._layer_state else []
            _dbg(f"refresh() order has {len(self._order)} items")
        finally:
            _dbg("refresh() calling endResetModel")
            self.endResetModel()
            _dbg("refresh() DONE")

    def get_order(self) -> list[str]:
        return list(self._order)

    # Note: ordering is mutated through LayerTreeState; model rebuild reflects state.

    def item_uuids_under(self, index: QtCore.QModelIndex) -> list[str]:
        """Get item UUIDs represented by index (group expands to all descendant items)."""
        node = self._layer_node_from_index(index)
        if not node:
            return []
        if node.is_item():
            return [node.uuid]
        if self._layer_state:
            return self._layer_state.get_group_items_recursive(node.uuid)
        return []

    # --- Qt Model Overrides ---

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: B008
        return 1

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: B008
        if not self._layer_state:
            return 0
        if not parent.isValid():
            return len(self._layer_state.get_root_nodes())
        node = self._layer_node_from_index(parent)
        if not node or not node.is_group():
            return 0
        return len(node.children)

    def index(
        self,
        row: int,
        column: int,
        parent: QtCore.QModelIndex = QtCore.QModelIndex(),  # noqa: B008
    ) -> QtCore.QModelIndex:
        if column != 0 or row < 0:
            return QtCore.QModelIndex()
        if not self._layer_state:
            return QtCore.QModelIndex()

        if not parent.isValid():
            roots = self._layer_state.get_root_nodes()
            if row >= len(roots):
                return QtCore.QModelIndex()
            node_uuid = roots[row].uuid
            # CRITICAL: Reuse existing tuple to prevent GC of object Qt indexes reference
            if node_uuid not in self._index_data:
                ptr_data = (node_uuid, self._layer_state.generation)
                self._index_data[node_uuid] = ptr_data
                _dbg(f"index({row}, {column}, root) -> NEW uuid={node_uuid[:8]}... gen={self._layer_state.generation}")
            else:
                ptr_data = self._index_data[node_uuid]
                _dbg(f"index({row}, {column}, root) -> REUSE uuid={node_uuid[:8]}...")
            return self.createIndex(row, column, ptr_data)

        parent_node = self._layer_node_from_index(parent)
        if not parent_node or not parent_node.is_group():
            return QtCore.QModelIndex()
        if row >= len(parent_node.children):
            return QtCore.QModelIndex()
        node_uuid = parent_node.children[row].uuid
        # CRITICAL: Reuse existing tuple to prevent GC of object Qt indexes reference
        if node_uuid not in self._index_data:
            ptr_data = (node_uuid, self._layer_state.generation)
            self._index_data[node_uuid] = ptr_data
            _dbg(f"index({row}, {column}, parent={parent_node.uuid[:8]}...) -> NEW uuid={node_uuid[:8]}...")
        else:
            ptr_data = self._index_data[node_uuid]
            _dbg(f"index({row}, {column}, parent={parent_node.uuid[:8]}...) -> REUSE uuid={node_uuid[:8]}...")
        return self.createIndex(row, column, ptr_data)

    def parent(self, index: QtCore.QModelIndex) -> QtCore.QModelIndex:  # noqa: A003
        if not self._layer_state:
            return QtCore.QModelIndex()
        node = self._layer_node_from_index(index)
        if not node or not node.parent:
            return QtCore.QModelIndex()
        parent_node = node.parent
        siblings = parent_node.parent.children if parent_node.parent else self._layer_state.get_root_nodes()
        try:
            row = siblings.index(parent_node)
        except ValueError:
            return QtCore.QModelIndex()
        # CRITICAL: Reuse existing tuple to prevent GC of object Qt indexes reference
        if parent_node.uuid not in self._index_data:
            ptr_data = (parent_node.uuid, self._layer_state.generation)
            self._index_data[parent_node.uuid] = ptr_data
        else:
            ptr_data = self._index_data[parent_node.uuid]
        return self.createIndex(row, 0, ptr_data)

    def data(self, index: QtCore.QModelIndex, role: int = int(QtCore.Qt.ItemDataRole.DisplayRole)) -> object:  # noqa: B008,E501
        node = self._layer_node_from_index(index)
        if not node:
            return None

        if role == int(QtCore.Qt.ItemDataRole.DisplayRole):
            if node.is_group():
                return node.name or "Group"
            return self._get_item_name(node.uuid)

        if role == int(IS_GROUP_ROLE):
            return node.is_group()

        if node.is_group() and role == int(GROUP_UUID_ROLE):
            return node.uuid
        if node.is_item() and role == int(ITEM_UUID_ROLE):
            return node.uuid

        if role == int(VISIBLE_ROLE):
            if node.is_group():
                return True  # UI uses toggle; we treat group as visible conceptually
            if item := self._uuid_to_item.get(node.uuid):
                return bool(item.isVisible())
            return True

        if role == int(LOCKED_ROLE):
            if node.is_group():
                return False
            if item := self._uuid_to_item.get(node.uuid):
                return bool(getattr(item, "_locked", False))
            return False

        return None

    def setData(self, index: QtCore.QModelIndex, value: object, role: int = int(QtCore.Qt.ItemDataRole.EditRole)) -> bool:  # noqa: B008,E501
        node = self._layer_node_from_index(index)
        if not node:
            return False

        if role == int(QtCore.Qt.ItemDataRole.EditRole):
            # Only groups are renameable here (items derive from component params)
            if node.is_group() and self._layer_state:
                new_name = str(value)
                self._layer_state.rename_group(node.uuid, new_name, emit=True)
                self.dataChanged.emit(index, index, [int(QtCore.Qt.ItemDataRole.DisplayRole)])
                return True
            return False

        if role == int(VISIBLE_ROLE):
            visible = bool(value)
            if not self._scene:
                return False
            if node.is_group():
                self._set_group_visible(node.uuid, visible)
            else:
                if item := self._uuid_to_item.get(node.uuid):
                    item.setVisible(visible)
            self.dataChanged.emit(index, index, [int(VISIBLE_ROLE)])
            return True

        if role == int(LOCKED_ROLE):
            locked = bool(value)
            if not self._scene:
                return False
            if node.is_group():
                self._set_group_locked(node.uuid, locked)
            else:
                if item := self._uuid_to_item.get(node.uuid):
                    if hasattr(item, "set_locked"):
                        item.set_locked(locked)
            self.dataChanged.emit(index, index, [int(LOCKED_ROLE)])
            return True

        return False

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlag:
        if not index.isValid():
            # Root supports drops
            return QtCore.Qt.ItemFlag.ItemIsDropEnabled

        node = self._layer_node_from_index(index)
        if not node:
            return QtCore.Qt.ItemFlag.NoItemFlags

        flags = (
            QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsDragEnabled
        )
        if node.is_group():
            flags |= QtCore.Qt.ItemFlag.ItemIsDropEnabled | QtCore.Qt.ItemFlag.ItemIsEditable
        return flags

    def supportedDropActions(self) -> QtCore.Qt.DropAction:
        return QtCore.Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [MIME_TYPE_LAYER_ITEMS]

    def mimeData(self, indexes: list[QtCore.QModelIndex]) -> QtCore.QMimeData:
        mime = QtCore.QMimeData()
        uuids = self._selected_item_uuids_from_indexes(indexes)
        mime.setData(MIME_TYPE_LAYER_ITEMS, ",".join(uuids).encode("utf-8"))
        return mime

    def dropMimeData(
        self,
        data: QtCore.QMimeData,
        action: QtCore.Qt.DropAction,
        row: int,
        column: int,
        parent: QtCore.QModelIndex,
    ) -> bool:
        if action != QtCore.Qt.DropAction.MoveAction:
            return False
        if not self._scene:
            return False
        if not data.hasFormat(MIME_TYPE_LAYER_ITEMS):
            return False

        raw = bytes(data.data(MIME_TYPE_LAYER_ITEMS)).decode("utf-8").strip()
        moved_uuids = [u for u in raw.split(",") if u]
        if not moved_uuids:
            return False

        target_parent_node = self._layer_node_from_index(parent) if parent.isValid() else None
        if target_parent_node and target_parent_node.is_item():
            return False  # cannot drop onto an item

        # Resolve destination list
        if not self._layer_state:
            return False
        dest_list = target_parent_node.children if target_parent_node else self._layer_state.get_root_nodes()
        insert_row = row if row >= 0 else len(dest_list)
        insert_row = max(0, min(insert_row, len(dest_list)))

        # Preserve relative order based on current traversal
        moved_uuids = self._sort_uuids_by_current_order(moved_uuids)

        cmds: list[Command] = []

        target_parent_uuid: str | None = (
            target_parent_node.uuid if (target_parent_node and target_parent_node.is_group()) else None
        )

        # Adjust insertion index when moving within the same parent: removing items above the drop
        # shifts the destination upward.
        adjusted_insert = insert_row
        for uuid in moved_uuids:
            pos = self._layer_state.get_parent_and_index(uuid)
            if pos and pos[0] == target_parent_uuid and pos[1] < insert_row:
                adjusted_insert -= 1
        adjusted_insert = max(0, adjusted_insert)

        for i, uuid in enumerate(moved_uuids):
            cmds.append(MoveNodeCommand(self._layer_state, uuid, target_parent_uuid, adjusted_insert + i))

        batch = BatchCommand(cmds)
        if self._undo_stack:
            self._undo_stack.push(batch)
        else:
            batch.execute()

        # Rebuild from authoritative LayerTreeState
        self.refresh()
        self.orderChanged.emit()
        return True

    # --- Helpers ---

    def _uuid_from_index(self, index: QtCore.QModelIndex) -> str | None:
        if not index.isValid():
            return None
        _dbg(f"_uuid_from_index: index.row={index.row()}, col={index.column()}, calling internalPointer...")
        try:
            ptr = index.internalPointer()
            _dbg(f"_uuid_from_index: ptr type={type(ptr).__name__}, ptr={ptr!r}")
        except Exception as e:
            _dbg(f"_uuid_from_index: EXCEPTION accessing internalPointer: {e}")
            traceback.print_exc()
            return None
        if isinstance(ptr, tuple) and len(ptr) == 2:
            uuid, gen = ptr
            if not isinstance(uuid, str) or not isinstance(gen, int):
                _dbg(f"_uuid_from_index: invalid tuple contents")
                return None
            if self._layer_state and gen != self._layer_state.generation:
                _dbg(f"_uuid_from_index: stale generation {gen} != {self._layer_state.generation}")
                return None
            return uuid
        _dbg(f"_uuid_from_index: unexpected ptr type, returning None")
        return ptr if isinstance(ptr, str) else None

    def _layer_node_from_index(self, index: QtCore.QModelIndex) -> LayerNode | None:
        if not self._layer_state:
            return None
        uuid = self._uuid_from_index(index)
        if not uuid:
            return None
        return self._layer_state.get_node(uuid)

    def _rebuild_caches(self) -> None:
        self._uuid_to_item.clear()
        if not self._scene:
            return
        for item in self._scene.items():
            if hasattr(item, "item_uuid") and hasattr(item, "type_name"):
                self._uuid_to_item[item.item_uuid] = item

    def _get_item_name(self, uuid: str) -> str:
        item = self._uuid_to_item.get(uuid)
        if not item:
            return "Item"
        if hasattr(item, "params") and hasattr(item.params, "name") and item.params.name:
            return str(item.params.name)
        return item.type_name.replace("_", " ").title() if hasattr(item, "type_name") else "Item"

    def _selected_item_uuids_from_indexes(self, indexes: list[QtCore.QModelIndex]) -> list[str]:
        # Unique UUIDs for item rows only, ignore group rows
        uuids: list[str] = []
        seen: set[str] = set()
        for idx in indexes:
            if idx.column() != 0:
                continue
            node = self._layer_node_from_index(idx)
            if not node or not node.is_item():
                continue
            if node.uuid not in seen:
                seen.add(node.uuid)
                uuids.append(node.uuid)
        return self._sort_uuids_by_current_order(uuids)

    def _sort_uuids_by_current_order(self, uuids: list[str]) -> list[str]:
        current = self._layer_state.get_all_items_in_order() if self._layer_state else []
        rank = {u: i for i, u in enumerate(current)}
        return sorted(uuids, key=lambda u: rank.get(u, 10**9))

    def _set_group_visible(self, group_uuid: str, visible: bool) -> None:
        if not self._scene or not self._layer_state:
            return
        for item_uuid in self._layer_state.get_group_items_recursive(group_uuid):
            if it := self._uuid_to_item.get(item_uuid):
                it.setVisible(visible)

    def _set_group_locked(self, group_uuid: str, locked: bool) -> None:
        if not self._scene or not self._layer_state:
            return
        for item_uuid in self._layer_state.get_group_items_recursive(group_uuid):
            if it := self._uuid_to_item.get(item_uuid):
                if hasattr(it, "set_locked"):
                    it.set_locked(locked)


