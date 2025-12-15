"""Layer tree model - single source of truth for layer hierarchy and z-order.

This model holds the authoritative tree structure of layers including groups.
Z-values are derived from this model, not the other way around.
"""

from __future__ import annotations

import uuid as uuid_module
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from PyQt6 import QtCore

if TYPE_CHECKING:
    from PyQt6 import QtWidgets


@dataclass
class LayerNode:
    """
    A node in the layer tree.
    
    Can be either an item (leaf) or a group (can have children).
    """
    
    uuid: str
    node_type: Literal["item", "group"]
    name: str | None = None  # Display name (used for groups, optional for items)
    children: list[LayerNode] = field(default_factory=list)
    collapsed: bool = False  # For groups: whether collapsed in tree view
    parent: LayerNode | None = field(default=None, repr=False)
    
    def is_group(self) -> bool:
        """Check if this node is a group."""
        return self.node_type == "group"
    
    def is_item(self) -> bool:
        """Check if this node is an item."""
        return self.node_type == "item"
    
    def get_index_in_parent(self) -> int:
        """Get this node's index within its parent's children (-1 if root)."""
        if self.parent is None:
            return -1
        try:
            return self.parent.children.index(self)
        except ValueError:
            return -1
    
    def get_all_item_uuids(self) -> list[str]:
        """Get all item UUIDs under this node (recursive for groups)."""
        if self.is_item():
            return [self.uuid]
        
        result: list[str] = []
        for child in self.children:
            result.extend(child.get_all_item_uuids())
        return result


class LayerTreeModel(QtCore.QObject):
    """
    Tree-structured model for layer hierarchy.
    
    This is the single source of truth for:
    - Layer order (z-order)
    - Group structure
    - Item-to-group relationships
    
    Z-values are derived from this model by the Z-Value Manager.
    
    Signals:
        structureChanged: Emitted when tree structure changes (add, remove, move, group)
    """
    
    structureChanged = QtCore.pyqtSignal()
    
    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._root_nodes: list[LayerNode] = []  # Top-level nodes
        self._uuid_to_node: dict[str, LayerNode] = {}  # Fast lookup
        self._scene: QtWidgets.QGraphicsScene | None = None
    
    def set_scene(self, scene: QtWidgets.QGraphicsScene | None) -> None:
        """Set the graphics scene (for item lookup)."""
        self._scene = scene
    
    # --- Node Access ---
    
    def get_node(self, uuid: str) -> LayerNode | None:
        """Get a node by UUID."""
        return self._uuid_to_node.get(uuid)
    
    def get_root_nodes(self) -> list[LayerNode]:
        """Get top-level nodes."""
        return list(self._root_nodes)
    
    def __contains__(self, uuid: str) -> bool:
        """Check if UUID is in the model."""
        return uuid in self._uuid_to_node
    
    def __len__(self) -> int:
        """Get total number of nodes (items + groups)."""
        return len(self._uuid_to_node)
    
    # --- Item Operations ---
    
    def add_item(
        self,
        uuid: str,
        parent_group: str | None = None,
        index: int = 0,
        emit: bool = True,
    ) -> LayerNode | None:
        """
        Add an item to the model.
        
        Args:
            uuid: Item UUID
            parent_group: Parent group UUID (None for top-level)
            index: Position within parent (0 = top)
            emit: Whether to emit structureChanged
            
        Returns:
            The created node, or None if UUID already exists
        """
        if uuid in self._uuid_to_node:
            return None  # Already exists
        
        node = LayerNode(uuid=uuid, node_type="item")
        self._uuid_to_node[uuid] = node
        
        if parent_group and parent_group in self._uuid_to_node:
            parent_node = self._uuid_to_node[parent_group]
            if parent_node.is_group():
                node.parent = parent_node
                index = max(0, min(index, len(parent_node.children)))
                parent_node.children.insert(index, node)
            else:
                # Parent is not a group, add to root
                index = max(0, min(index, len(self._root_nodes)))
                self._root_nodes.insert(index, node)
        else:
            # Add to root
            index = max(0, min(index, len(self._root_nodes)))
            self._root_nodes.insert(index, node)
        
        if emit:
            self.structureChanged.emit()
        
        return node
    
    def remove_item(self, uuid: str, emit: bool = True) -> bool:
        """
        Remove an item from the model.
        
        Args:
            uuid: Item UUID to remove
            emit: Whether to emit structureChanged
            
        Returns:
            True if removed, False if not found
        """
        node = self._uuid_to_node.get(uuid)
        if not node or not node.is_item():
            return False
        
        # Remove from parent
        if node.parent:
            node.parent.children.remove(node)
        else:
            self._root_nodes.remove(node)
        
        del self._uuid_to_node[uuid]
        
        if emit:
            self.structureChanged.emit()
        
        return True
    
    def move_item(
        self,
        uuid: str,
        target_parent: str | None,
        index: int,
        emit: bool = True,
    ) -> bool:
        """
        Move an item to a new position.
        
        Args:
            uuid: Item UUID to move
            target_parent: Target parent group UUID (None for root)
            index: Position within target parent
            emit: Whether to emit structureChanged
            
        Returns:
            True if moved, False if not found
        """
        node = self._uuid_to_node.get(uuid)
        if not node:
            return False
        
        # Get target parent node
        target_parent_node: LayerNode | None = None
        if target_parent:
            target_parent_node = self._uuid_to_node.get(target_parent)
            if target_parent_node and not target_parent_node.is_group():
                target_parent_node = None  # Can't move into non-group
        
        # Remove from current parent
        if node.parent:
            node.parent.children.remove(node)
        elif node in self._root_nodes:
            self._root_nodes.remove(node)
        
        # Add to new parent
        if target_parent_node:
            node.parent = target_parent_node
            index = max(0, min(index, len(target_parent_node.children)))
            target_parent_node.children.insert(index, node)
        else:
            node.parent = None
            index = max(0, min(index, len(self._root_nodes)))
            self._root_nodes.insert(index, node)
        
        if emit:
            self.structureChanged.emit()
        
        return True
    
    # --- Group Operations ---
    
    def create_group(
        self,
        name: str,
        item_uuids: list[str],
        parent_group: str | None = None,
        emit: bool = True,
    ) -> str | None:
        """
        Create a group containing the specified items.
        
        Args:
            name: Group name
            item_uuids: UUIDs of items to include in group
            parent_group: Parent group UUID (None for top-level)
            emit: Whether to emit structureChanged
            
        Returns:
            Group UUID, or None if failed
        """
        # Validate items exist
        nodes_to_group = [self._uuid_to_node.get(uuid) for uuid in item_uuids]
        if not all(nodes_to_group):
            return None  # Some items don't exist
        
        # Create group node
        group_uuid = str(uuid_module.uuid4())
        group_node = LayerNode(uuid=group_uuid, node_type="group", name=name)
        self._uuid_to_node[group_uuid] = group_node
        
        # Find insertion position (where first item was)
        first_node = nodes_to_group[0]
        if first_node.parent:
            insert_index = first_node.parent.children.index(first_node)
            group_node.parent = first_node.parent
            first_node.parent.children.insert(insert_index, group_node)
        else:
            insert_index = self._root_nodes.index(first_node) if first_node in self._root_nodes else 0
            self._root_nodes.insert(insert_index, group_node)
        
        # Move items into group
        for node in nodes_to_group:
            if node:
                # Remove from current parent
                if node.parent:
                    node.parent.children.remove(node)
                elif node in self._root_nodes:
                    self._root_nodes.remove(node)
                
                # Add to group
                node.parent = group_node
                group_node.children.append(node)
        
        if emit:
            self.structureChanged.emit()
        
        return group_uuid
    
    def delete_group(self, group_uuid: str, emit: bool = True) -> bool:
        """
        Delete a group, moving its children to the group's parent.
        
        Args:
            group_uuid: Group UUID to delete
            emit: Whether to emit structureChanged
            
        Returns:
            True if deleted, False if not found or not a group
        """
        node = self._uuid_to_node.get(group_uuid)
        if not node or not node.is_group():
            return False
        
        # Get parent and index
        parent = node.parent
        if parent:
            index = parent.children.index(node)
            parent.children.remove(node)
            # Move children to parent at same position
            for i, child in enumerate(node.children):
                child.parent = parent
                parent.children.insert(index + i, child)
        else:
            index = self._root_nodes.index(node) if node in self._root_nodes else 0
            self._root_nodes.remove(node)
            # Move children to root at same position
            for i, child in enumerate(node.children):
                child.parent = None
                self._root_nodes.insert(index + i, child)
        
        del self._uuid_to_node[group_uuid]
        
        if emit:
            self.structureChanged.emit()
        
        return True
    
    def rename_group(self, group_uuid: str, name: str, emit: bool = True) -> bool:
        """
        Rename a group.
        
        Args:
            group_uuid: Group UUID
            name: New name
            emit: Whether to emit structureChanged
            
        Returns:
            True if renamed, False if not found or not a group
        """
        node = self._uuid_to_node.get(group_uuid)
        if not node or not node.is_group():
            return False
        
        node.name = name
        
        if emit:
            self.structureChanged.emit()
        
        return True
    
    def set_group_collapsed(self, group_uuid: str, collapsed: bool) -> bool:
        """
        Set group collapsed state.
        
        Args:
            group_uuid: Group UUID
            collapsed: Whether collapsed
            
        Returns:
            True if set, False if not found or not a group
        """
        node = self._uuid_to_node.get(group_uuid)
        if not node or not node.is_group():
            return False
        
        node.collapsed = collapsed
        return True
    
    def get_item_group(self, item_uuid: str) -> LayerNode | None:
        """Get the group containing an item (None if at root level)."""
        node = self._uuid_to_node.get(item_uuid)
        if not node:
            return None
        
        parent = node.parent
        while parent:
            if parent.is_group():
                return parent
            parent = parent.parent
        
        return None
    
    def add_item_to_group(
        self,
        item_uuid: str,
        group_uuid: str,
        index: int | None = None,
        emit: bool = True,
    ) -> bool:
        """
        Add an item to a group.
        
        Args:
            item_uuid: Item UUID
            group_uuid: Group UUID
            index: Position in group (None for end)
            emit: Whether to emit structureChanged
            
        Returns:
            True if added, False if failed
        """
        item_node = self._uuid_to_node.get(item_uuid)
        group_node = self._uuid_to_node.get(group_uuid)
        
        if not item_node or not group_node or not group_node.is_group():
            return False
        
        # Remove from current parent
        if item_node.parent:
            item_node.parent.children.remove(item_node)
        elif item_node in self._root_nodes:
            self._root_nodes.remove(item_node)
        
        # Add to group
        item_node.parent = group_node
        if index is None:
            group_node.children.append(item_node)
        else:
            index = max(0, min(index, len(group_node.children)))
            group_node.children.insert(index, item_node)
        
        if emit:
            self.structureChanged.emit()
        
        return True
    
    def remove_item_from_group(self, item_uuid: str, emit: bool = True) -> bool:
        """
        Remove an item from its group, moving it to root level.
        
        Args:
            item_uuid: Item UUID
            emit: Whether to emit structureChanged
            
        Returns:
            True if removed, False if not in a group
        """
        item_node = self._uuid_to_node.get(item_uuid)
        if not item_node or not item_node.parent:
            return False
        
        # Get position in parent
        parent = item_node.parent
        index = parent.children.index(item_node)
        parent.children.remove(item_node)
        
        # Find position in root (after parent's root position)
        if parent.parent:
            # Parent is nested, find root ancestor
            root_ancestor = parent
            while root_ancestor.parent:
                root_ancestor = root_ancestor.parent
            root_index = self._root_nodes.index(root_ancestor) + 1 if root_ancestor in self._root_nodes else 0
        else:
            root_index = self._root_nodes.index(parent) + 1 if parent in self._root_nodes else 0
        
        # Add to root
        item_node.parent = None
        self._root_nodes.insert(root_index, item_node)
        
        if emit:
            self.structureChanged.emit()
        
        return True
    
    # --- Traversal ---
    
    def get_all_items_in_order(self) -> list[str]:
        """
        Get all item UUIDs in z-order (top to bottom).
        
        Uses depth-first traversal: parent comes before children.
        
        Returns:
            List of item UUIDs in order (first = top/highest z)
        """
        result: list[str] = []
        
        def traverse(nodes: list[LayerNode]) -> None:
            for node in nodes:
                if node.is_item():
                    result.append(node.uuid)
                elif node.is_group():
                    traverse(node.children)
        
        traverse(self._root_nodes)
        return result
    
    def get_all_groups(self) -> list[LayerNode]:
        """Get all group nodes."""
        return [node for node in self._uuid_to_node.values() if node.is_group()]
    
    def get_root_groups(self) -> list[LayerNode]:
        """Get top-level groups."""
        return [node for node in self._root_nodes if node.is_group()]
    
    # --- Batch Operations ---
    
    def sync_with_scene(self) -> bool:
        """
        Sync model with scene items (for migration/initialization).
        
        Adds new items and removes deleted items.
        
        Returns:
            True if changes were made
        """
        if not self._scene:
            return False
        
        # Get current scene item UUIDs
        scene_uuids: set[str] = set()
        for item in self._scene.items():
            if hasattr(item, "item_uuid") and hasattr(item, "type_name"):
                scene_uuids.add(item.item_uuid)
        
        # Get current model item UUIDs (not groups)
        model_item_uuids = {uuid for uuid, node in self._uuid_to_node.items() if node.is_item()}
        
        new_uuids = scene_uuids - model_item_uuids
        deleted_uuids = model_item_uuids - scene_uuids
        
        if not new_uuids and not deleted_uuids:
            return False
        
        # Add new items at top (without emitting)
        for uuid in new_uuids:
            self.add_item(uuid, index=0, emit=False)
        
        # Remove deleted items (without emitting)
        for uuid in deleted_uuids:
            self.remove_item(uuid, emit=False)
        
        # Single emit
        self.structureChanged.emit()
        return True
    
    def reorder_root_nodes(self, new_order: list[str], emit: bool = True) -> None:
        """
        Reorder top-level nodes.
        
        Args:
            new_order: List of UUIDs in new order
            emit: Whether to emit structureChanged
        """
        # Build new root list based on order
        new_roots: list[LayerNode] = []
        seen: set[str] = set()
        
        for uuid in new_order:
            if uuid in self._uuid_to_node and uuid not in seen:
                node = self._uuid_to_node[uuid]
                if node.parent is None:  # Only root nodes
                    new_roots.append(node)
                    seen.add(uuid)
        
        # Add any remaining root nodes not in new_order
        for node in self._root_nodes:
            if node.uuid not in seen:
                new_roots.append(node)
        
        self._root_nodes = new_roots
        
        if emit:
            self.structureChanged.emit()
    
    def clear(self, emit: bool = True) -> None:
        """Clear all nodes from the model."""
        self._root_nodes.clear()
        self._uuid_to_node.clear()
        
        if emit:
            self.structureChanged.emit()
    
    # --- Serialization ---
    
    def to_dict(self) -> dict:
        """
        Serialize model to dictionary.
        
        Returns:
            Dictionary representation of the model
        """
        def node_to_dict(node: LayerNode) -> dict:
            data = {
                "uuid": node.uuid,
                "type": node.node_type,
            }
            if node.name:
                data["name"] = node.name
            if node.collapsed:
                data["collapsed"] = node.collapsed
            if node.children:
                data["children"] = [node_to_dict(child) for child in node.children]
            return data
        
        return {
            "version": 1,
            "nodes": [node_to_dict(node) for node in self._root_nodes],
        }
    
    @classmethod
    def from_dict(cls, data: dict, parent: QtCore.QObject | None = None) -> LayerTreeModel:
        """
        Deserialize model from dictionary.
        
        Args:
            data: Dictionary representation
            parent: Parent QObject
            
        Returns:
            New LayerTreeModel instance
        """
        model = cls(parent)
        
        if not data or data.get("version") != 1:
            return model
        
        def dict_to_node(node_data: dict, parent_node: LayerNode | None = None) -> LayerNode:
            node = LayerNode(
                uuid=node_data["uuid"],
                node_type=node_data["type"],
                name=node_data.get("name"),
                collapsed=node_data.get("collapsed", False),
                parent=parent_node,
            )
            model._uuid_to_node[node.uuid] = node
            
            for child_data in node_data.get("children", []):
                child = dict_to_node(child_data, node)
                node.children.append(child)
            
            return node
        
        for node_data in data.get("nodes", []):
            node = dict_to_node(node_data)
            model._root_nodes.append(node)
        
        return model
    
    @classmethod
    def from_z_values(
        cls,
        scene: QtWidgets.QGraphicsScene,
        parent: QtCore.QObject | None = None,
    ) -> LayerTreeModel:
        """
        Build model from scene items' z-values (for legacy file migration).
        
        Args:
            scene: Graphics scene with items
            parent: Parent QObject
            
        Returns:
            New LayerTreeModel with items ordered by z-value
        """
        model = cls(parent)
        model._scene = scene
        
        # Collect items with z-values
        items_with_z: list[tuple[float, str]] = []
        for item in scene.items():
            if hasattr(item, "item_uuid") and hasattr(item, "type_name"):
                items_with_z.append((item.zValue(), item.item_uuid))
        
        # Sort by z-value descending (highest z = first in list = top)
        items_with_z.sort(key=lambda x: x[0], reverse=True)
        
        # Add items in order
        for _, uuid in items_with_z:
            model.add_item(uuid, index=len(model._root_nodes), emit=False)
        
        return model


