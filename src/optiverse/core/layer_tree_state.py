"""Authoritative layer hierarchy + z-order state (single source of truth).

This replaces legacy group management and any z-order-as-input behavior.
Scene z-values must be treated as derived output from this model.

Data model:
- Nodes are either 'group' or 'item'
- Groups can contain child groups and item nodes
- Z-order is defined by a stable depth-first traversal of root nodes
  (parent before children; items appear where they are in the tree)
"""

from __future__ import annotations

import uuid as uuid_module
from dataclasses import dataclass, field
from typing import Any, Literal

from PyQt6 import QtCore

NodeType = Literal["group", "item"]


@dataclass
class LayerNode:
    uuid: str
    node_type: NodeType
    name: str | None = None
    collapsed: bool = False
    visible: bool = True
    locked: bool = False
    parent: LayerNode | None = field(default=None, repr=False)
    children: list[LayerNode] = field(default_factory=list, repr=False)

    def is_group(self) -> bool:
        return self.node_type == "group"

    def is_item(self) -> bool:
        return self.node_type == "item"


class LayerTreeState(QtCore.QObject):
    """Single source of truth for layers (hierarchy + ordering + UI collapsed state)."""

    changed = QtCore.pyqtSignal()

    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._roots: list[LayerNode] = []
        self._uuid_to_node: dict[str, LayerNode] = {}
        self._suppress_emit = 0
        # Monotonic change counter. Consumers can use this to detect stale indices/caches.
        self._generation = 0

    @property
    def generation(self) -> int:
        """Monotonic version of the state; increments on meaningful changes."""
        return self._generation

    def _bump_generation(self) -> None:
        self._generation += 1

    # --- Access ---

    def get_root_nodes(self) -> list[LayerNode]:
        return list(self._roots)

    def get_node(self, uuid: str) -> LayerNode | None:
        return self._uuid_to_node.get(uuid)

    def __contains__(self, uuid: str) -> bool:
        return uuid in self._uuid_to_node

    # --- Ordering / traversal ---

    def get_all_items_in_order(self) -> list[str]:
        """Depth-first traversal order (top to bottom)."""
        out: list[str] = []

        def walk(nodes: list[LayerNode]) -> None:
            for n in nodes:
                if n.is_item():
                    out.append(n.uuid)
                else:
                    walk(n.children)

        walk(self._roots)
        return out

    def get_parent_and_index(self, uuid: str) -> tuple[str | None, int] | None:
        """Return (parent_uuid, index) for a node; parent_uuid None means root."""
        node = self._uuid_to_node.get(uuid)
        if not node:
            return None
        if node.parent:
            try:
                return node.parent.uuid, node.parent.children.index(node)
            except ValueError:
                return node.parent.uuid, 0
        try:
            return None, self._roots.index(node)
        except ValueError:
            return None, 0

    # --- Mutations ---

    def clear(self, emit: bool = True) -> None:
        self._roots.clear()
        self._uuid_to_node.clear()
        if emit:
            self._emit_changed()

    def add_item(
        self,
        item_uuid: str,
        parent_group_uuid: str | None = None,
        index: int = 0,
        emit: bool = True,
    ) -> None:
        if item_uuid in self._uuid_to_node:
            return
        node = LayerNode(uuid=item_uuid, node_type="item")
        self._uuid_to_node[item_uuid] = node
        self._insert_node(node, parent_group_uuid, index)
        if emit:
            self._emit_changed()

    def remove_item(self, item_uuid: str, emit: bool = True) -> None:
        node = self._uuid_to_node.get(item_uuid)
        if not node or not node.is_item():
            return
        self._detach_node(node)
        del self._uuid_to_node[item_uuid]
        if emit:
            self._emit_changed()

    def create_group(
        self,
        name: str,
        parent_group_uuid: str | None = None,
        index: int = 0,
        group_uuid: str | None = None,
        emit: bool = True,
    ) -> str:
        gid = group_uuid or str(uuid_module.uuid4())
        if gid in self._uuid_to_node:
            return gid
        node = LayerNode(uuid=gid, node_type="group", name=name)
        self._uuid_to_node[gid] = node
        self._insert_node(node, parent_group_uuid, index)
        if emit:
            self._emit_changed()
        return gid

    def delete_group(self, group_uuid: str, emit: bool = True) -> None:
        node = self._uuid_to_node.get(group_uuid)
        if not node or not node.is_group():
            return
        # Reparent children to this group's parent at this group's position
        parent = node.parent
        siblings = parent.children if parent else self._roots
        try:
            idx = siblings.index(node)
        except ValueError:
            idx = 0
        self._detach_node(node)
        for child in list(node.children):
            child.parent = parent
        siblings[idx:idx] = node.children
        node.children.clear()
        del self._uuid_to_node[group_uuid]
        if emit:
            self._emit_changed()

    def rename_group(self, group_uuid: str, name: str, emit: bool = True) -> None:
        node = self._uuid_to_node.get(group_uuid)
        if not node or not node.is_group():
            return
        node.name = name
        if emit:
            self._emit_changed()

    def set_group_collapsed(self, group_uuid: str, collapsed: bool, emit: bool = True) -> None:
        node = self._uuid_to_node.get(group_uuid)
        if not node or not node.is_group():
            return
        node.collapsed = collapsed
        if emit:
            self._emit_changed()

    def move_node(
        self, uuid: str, target_parent_group_uuid: str | None, index: int, emit: bool = True
    ) -> None:
        node = self._uuid_to_node.get(uuid)
        if not node:
            return
        self._detach_node(node)
        self._insert_node(node, target_parent_group_uuid, index)
        if emit:
            self._emit_changed()

    def move_item_to_group(
        self, item_uuid: str, group_uuid: str | None, index: int | None = None, emit: bool = True
    ) -> None:
        node = self._uuid_to_node.get(item_uuid)
        if not node or not node.is_item():
            return
        self._detach_node(node)
        if index is None:
            index = 10**9
        self._insert_node(node, group_uuid, index)
        if emit:
            self._emit_changed()

    def move_node_up(self, uuid: str, emit: bool = True) -> bool:
        """Move node earlier in sibling list (higher z-order). Returns True if moved."""
        node = self._uuid_to_node.get(uuid)
        if not node:
            return False
        siblings = node.parent.children if node.parent else self._roots
        try:
            idx = siblings.index(node)
        except ValueError:
            return False
        if idx == 0:
            return False  # Already at top
        # Swap with previous sibling
        siblings[idx], siblings[idx - 1] = siblings[idx - 1], siblings[idx]
        if emit:
            self._emit_changed()
        return True

    def move_node_down(self, uuid: str, emit: bool = True) -> bool:
        """Move node later in sibling list (lower z-order). Returns True if moved."""
        node = self._uuid_to_node.get(uuid)
        if not node:
            return False
        siblings = node.parent.children if node.parent else self._roots
        try:
            idx = siblings.index(node)
        except ValueError:
            return False
        if idx >= len(siblings) - 1:
            return False  # Already at bottom
        # Swap with next sibling
        siblings[idx], siblings[idx + 1] = siblings[idx + 1], siblings[idx]
        if emit:
            self._emit_changed()
        return True

    def move_node_to_front(self, uuid: str, emit: bool = True) -> bool:
        """Move node to first position in sibling list (highest z-order). Returns True if moved."""
        node = self._uuid_to_node.get(uuid)
        if not node:
            return False
        siblings = node.parent.children if node.parent else self._roots
        try:
            idx = siblings.index(node)
        except ValueError:
            return False
        if idx == 0:
            return False  # Already at front
        siblings.pop(idx)
        siblings.insert(0, node)
        if emit:
            self._emit_changed()
        return True

    def move_node_to_back(self, uuid: str, emit: bool = True) -> bool:
        """Move node to last position in sibling list (lowest z-order). Returns True if moved."""
        node = self._uuid_to_node.get(uuid)
        if not node:
            return False
        siblings = node.parent.children if node.parent else self._roots
        try:
            idx = siblings.index(node)
        except ValueError:
            return False
        if idx >= len(siblings) - 1:
            return False  # Already at back
        siblings.pop(idx)
        siblings.append(node)
        if emit:
            self._emit_changed()
        return True

    def apply_z_order_operation(self, uuids: list[str], operation: str) -> None:
        """Apply a z-order operation to multiple items.

        Args:
            uuids: List of item UUIDs to move
            operation: One of "bring_forward", "send_backward", "bring_to_front", "send_to_back"
        """
        if not uuids:
            return

        self.begin_update()
        try:
            if operation == "bring_forward":
                for uuid in reversed(uuids):
                    self.move_node_up(uuid, emit=False)
            elif operation == "send_backward":
                for uuid in uuids:
                    self.move_node_down(uuid, emit=False)
            elif operation == "bring_to_front":
                for uuid in reversed(uuids):
                    self.move_node_to_front(uuid, emit=False)
            elif operation == "send_to_back":
                for uuid in uuids:
                    self.move_node_to_back(uuid, emit=False)
        finally:
            self.end_update()

    def get_group_for_item(self, item_uuid: str) -> str | None:
        node = self._uuid_to_node.get(item_uuid)
        if not node:
            return None
        p = node.parent
        while p:
            if p.is_group():
                return p.uuid
            p = p.parent
        return None

    def get_group_items_recursive(self, group_uuid: str) -> list[str]:
        node = self._uuid_to_node.get(group_uuid)
        if not node or not node.is_group():
            return []
        out: list[str] = []

        def walk(n: LayerNode) -> None:
            for c in n.children:
                if c.is_item():
                    out.append(c.uuid)
                else:
                    walk(c)

        walk(node)
        return out

    def is_effectively_visible(self, uuid: str) -> bool:
        """Returns True if node AND all ancestors are visible (Photoshop-style)."""
        node = self._uuid_to_node.get(uuid)
        while node:
            if not node.visible:
                return False
            node = node.parent
        return True

    def is_effectively_locked(self, uuid: str) -> bool:
        """Returns True if node OR any ancestor is locked."""
        node = self._uuid_to_node.get(uuid)
        while node:
            if node.locked:
                return True
            node = node.parent
        return False

    def set_node_visible(self, uuid: str, visible: bool, emit: bool = True) -> None:
        """Set visibility on a node."""
        node = self._uuid_to_node.get(uuid)
        if node:
            node.visible = visible
            if emit:
                self._emit_changed()

    def set_node_locked(self, uuid: str, locked: bool, emit: bool = True) -> None:
        """Set locked state on a node."""
        node = self._uuid_to_node.get(uuid)
        if node:
            node.locked = locked
            if emit:
                self._emit_changed()

    # --- Serialization ---

    def to_dict(self) -> dict[str, Any]:
        def node_to_dict(n: LayerNode) -> dict[str, Any]:
            d: dict[str, Any] = {"uuid": n.uuid, "type": n.node_type}
            if n.name is not None:
                d["name"] = n.name
            if n.collapsed:
                d["collapsed"] = True
            if not n.visible:
                d["visible"] = False
            if n.locked:
                d["locked"] = True
            if n.children:
                d["children"] = [node_to_dict(c) for c in n.children]
            return d

        return {"version": 1, "nodes": [node_to_dict(n) for n in self._roots]}

    @classmethod
    def from_dict(cls, data: dict, parent: QtCore.QObject | None = None) -> LayerTreeState:
        st = cls(parent)
        if not data or data.get("version") != 1:
            return st

        def dict_to_node(d: dict, parent_node: LayerNode | None) -> LayerNode:
            node = LayerNode(
                uuid=d["uuid"],
                node_type=d["type"],
                name=d.get("name"),
                collapsed=bool(d.get("collapsed", False)),
                visible=bool(d.get("visible", True)),
                locked=bool(d.get("locked", False)),
                parent=parent_node,
            )
            st._uuid_to_node[node.uuid] = node
            for child_d in d.get("children", []) or []:
                child = dict_to_node(child_d, node)
                node.children.append(child)
            return node

        for nd in data.get("nodes", []) or []:
            st._roots.append(dict_to_node(nd, None))
        return st

    def replace_from(self, other: LayerTreeState, emit: bool = True) -> None:
        """
        Replace all state with `other` (used for load/migration) without changing
        object identity.
        """
        self._roots = other._roots
        self._uuid_to_node = other._uuid_to_node
        if emit:
            self._emit_changed()

    def begin_update(self) -> None:
        """Suppress changed emissions until end_update()."""
        self._suppress_emit += 1

    def end_update(self) -> None:
        """Re-enable changed emissions and emit once."""
        if self._suppress_emit > 0:
            self._suppress_emit -= 1
        if self._suppress_emit == 0:
            self._emit_changed()

    @classmethod
    def from_legacy(
        cls,
        groups: list[dict],
        items_with_z: list[tuple[float, str]],
        parent: QtCore.QObject | None = None,
    ) -> LayerTreeState:
        """Build from legacy `groups` list + (z, uuid) ordering."""
        st = cls(parent)

        # Sort items by z desc (top first)
        items_with_z = sorted(items_with_z, key=lambda t: t[0], reverse=True)
        item_order = [uuid for _, uuid in items_with_z]

        # Build group nodes
        group_nodes: dict[str, LayerNode] = {}
        for g in groups or []:
            gid = str(g.get("group_uuid") or uuid_module.uuid4())
            node = LayerNode(
                uuid=gid,
                node_type="group",
                name=g.get("name", "Group"),
                collapsed=bool(g.get("collapsed", False)),
                parent=None,
            )
            group_nodes[gid] = node
            st._uuid_to_node[gid] = node

        # Parent relationships between groups
        for g in groups or []:
            gid = str(g.get("group_uuid"))
            if gid not in group_nodes:
                continue
            parent_gid = g.get("parent_group_uuid")
            if parent_gid and str(parent_gid) in group_nodes:
                parent_node = group_nodes[str(parent_gid)]
                child_node = group_nodes[gid]
                child_node.parent = parent_node
                parent_node.children.append(child_node)

        # Root groups are those without parent
        root_groups = [n for n in group_nodes.values() if n.parent is None]
        # Place root groups first; their internal ordering will be filled with items by z-order
        st._roots.extend(root_groups)

        # Track grouped item uuids
        grouped_items: set[str] = set()
        group_items_map: dict[str, set[str]] = {}
        for g in groups or []:
            gid = str(g.get("group_uuid"))
            uuids = set(g.get("item_uuids", []) or [])
            group_items_map[gid] = uuids
            grouped_items |= uuids

        # Add item nodes into the correct group in z-order
        for uuid in item_order:
            if uuid in grouped_items:
                # Find the group this item belongs to (legacy format assumes one group per item)
                owner_gid = None
                for gid, uuids in group_items_map.items():
                    if uuid in uuids:
                        owner_gid = gid
                        break
                if owner_gid and owner_gid in group_nodes:
                    parent_node = group_nodes[owner_gid]
                    item_node = LayerNode(uuid=uuid, node_type="item", parent=parent_node)
                    st._uuid_to_node[uuid] = item_node
                    parent_node.children.append(item_node)
                    continue

            # Ungrouped → root
            item_node = LayerNode(uuid=uuid, node_type="item", parent=None)
            st._uuid_to_node[uuid] = item_node
            st._roots.append(item_node)

        return st

    # --- internal helpers ---

    def _detach_node(self, node: LayerNode) -> None:
        if node.parent:
            if node in node.parent.children:
                node.parent.children.remove(node)
        else:
            if node in self._roots:
                self._roots.remove(node)
        node.parent = None

    def _insert_node(self, node: LayerNode, parent_group_uuid: str | None, index: int) -> None:
        parent_node: LayerNode | None = None
        if parent_group_uuid:
            pn = self._uuid_to_node.get(parent_group_uuid)
            if pn and pn.is_group():
                parent_node = pn
        siblings = parent_node.children if parent_node else self._roots
        node.parent = parent_node
        idx = max(0, min(index, len(siblings)))
        siblings.insert(idx, node)

    def _emit_changed(self) -> None:
        if self._suppress_emit > 0:
            return
        self._bump_generation()
        self.changed.emit()


