"""
Tests for auto-deletion of empty groups when their last member is removed.

Covers:
- Single item deletion leaving a group empty
- Bulk deletion leaving a group empty
- Nested groups cascading to empty
- Linked groups are NOT auto-deleted
- Undo restores groups correctly
- Redo re-deletes groups correctly
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from optiverse.core.layer_tree_state import LayerTreeState, LinkMetadata
from optiverse.core.undo_commands import RemoveItemCommand, RemoveMultipleItemsCommand
from optiverse.core.undo_stack import UndoStack


def _make_item(uuid: str) -> MagicMock:
    """Create a mock graphics item with a given item_uuid."""
    item = MagicMock()
    item.item_uuid = uuid
    return item


def _make_scene(items: list) -> MagicMock:
    """Create a mock scene whose items() returns the given list."""
    scene = MagicMock()
    scene.items.return_value = list(items)
    return scene


@pytest.fixture
def layer_state():
    return LayerTreeState()


@pytest.fixture
def stack():
    return UndoStack()


class TestSingleDeleteAutoRemovesGroup:
    """Removing the last item from a group auto-deletes the group."""

    def test_group_deleted_when_last_item_removed(self, layer_state):
        item = _make_item("A")
        scene = _make_scene([item])
        gid = layer_state.create_group("G1", emit=False)
        layer_state.add_item("A", gid, 0, emit=False)

        cmd = RemoveItemCommand(scene, item, layer_state)
        cmd.execute()

        assert layer_state.get_node(gid) is None

    def test_group_not_deleted_when_siblings_remain(self, layer_state):
        item1 = _make_item("A")
        item2 = _make_item("B")
        scene = _make_scene([item1, item2])
        gid = layer_state.create_group("G1", emit=False)
        layer_state.add_item("A", gid, 0, emit=False)
        layer_state.add_item("B", gid, 1, emit=False)

        cmd = RemoveItemCommand(scene, item1, layer_state)
        cmd.execute()

        assert layer_state.get_node(gid) is not None
        assert layer_state.get_group_items_recursive(gid) == ["B"]

    def test_undo_restores_group_and_item(self, layer_state):
        item = _make_item("A")
        scene = _make_scene([item])
        gid = layer_state.create_group("G1", emit=False)
        layer_state.add_item("A", gid, 0, emit=False)

        cmd = RemoveItemCommand(scene, item, layer_state)
        cmd.execute()

        assert layer_state.get_node(gid) is None

        cmd.undo()

        node = layer_state.get_node(gid)
        assert node is not None
        assert node.is_group()
        assert node.name == "G1"
        assert layer_state.get_group_items_recursive(gid) == ["A"]

    def test_redo_re_deletes_group(self, layer_state, stack):
        item = _make_item("A")
        scene = _make_scene([item])
        gid = layer_state.create_group("G1", emit=False)
        layer_state.add_item("A", gid, 0, emit=False)

        cmd = RemoveItemCommand(scene, item, layer_state)
        stack.push(cmd)

        assert layer_state.get_node(gid) is None

        stack.undo()
        assert layer_state.get_node(gid) is not None

        stack.redo()
        assert layer_state.get_node(gid) is None

    def test_ungrouped_item_delete_no_crash(self, layer_state):
        """Deleting an item at root level (no group) should not crash."""
        item = _make_item("A")
        scene = _make_scene([item])
        layer_state.add_item("A", None, 0, emit=False)

        cmd = RemoveItemCommand(scene, item, layer_state)
        cmd.execute()

        assert layer_state.get_node("A") is None

        cmd.undo()
        assert layer_state.get_node("A") is not None


class TestBulkDeleteAutoRemovesGroup:
    """Removing all items from a group via bulk delete auto-deletes the group."""

    def test_group_deleted_when_all_members_removed(self, layer_state):
        item1 = _make_item("A")
        item2 = _make_item("B")
        scene = _make_scene([item1, item2])
        gid = layer_state.create_group("G1", emit=False)
        layer_state.add_item("A", gid, 0, emit=False)
        layer_state.add_item("B", gid, 1, emit=False)

        cmd = RemoveMultipleItemsCommand(scene, [item1, item2], layer_state)
        cmd.execute()

        assert layer_state.get_node(gid) is None

    def test_group_not_deleted_when_some_members_remain(self, layer_state):
        item1 = _make_item("A")
        item2 = _make_item("B")
        item3 = _make_item("C")
        scene = _make_scene([item1, item2, item3])
        gid = layer_state.create_group("G1", emit=False)
        layer_state.add_item("A", gid, 0, emit=False)
        layer_state.add_item("B", gid, 1, emit=False)
        layer_state.add_item("C", gid, 2, emit=False)

        cmd = RemoveMultipleItemsCommand(scene, [item1, item2], layer_state)
        cmd.execute()

        assert layer_state.get_node(gid) is not None
        assert layer_state.get_group_items_recursive(gid) == ["C"]

    def test_undo_restores_group_and_all_items(self, layer_state):
        item1 = _make_item("A")
        item2 = _make_item("B")
        scene = _make_scene([item1, item2])
        gid = layer_state.create_group("G1", emit=False)
        layer_state.add_item("A", gid, 0, emit=False)
        layer_state.add_item("B", gid, 1, emit=False)

        cmd = RemoveMultipleItemsCommand(scene, [item1, item2], layer_state)
        cmd.execute()

        assert layer_state.get_node(gid) is None

        cmd.undo()

        assert layer_state.get_node(gid) is not None
        members = layer_state.get_group_items_recursive(gid)
        assert "A" in members
        assert "B" in members

    def test_multiple_groups_cleaned_up(self, layer_state):
        """Items from different groups: both groups should be cleaned if empty."""
        item1 = _make_item("A")
        item2 = _make_item("B")
        scene = _make_scene([item1, item2])
        g1 = layer_state.create_group("G1", emit=False)
        g2 = layer_state.create_group("G2", emit=False)
        layer_state.add_item("A", g1, 0, emit=False)
        layer_state.add_item("B", g2, 0, emit=False)

        cmd = RemoveMultipleItemsCommand(scene, [item1, item2], layer_state)
        cmd.execute()

        assert layer_state.get_node(g1) is None
        assert layer_state.get_node(g2) is None

    def test_undo_multiple_groups_restored(self, layer_state):
        item1 = _make_item("A")
        item2 = _make_item("B")
        scene = _make_scene([item1, item2])
        g1 = layer_state.create_group("G1", emit=False)
        g2 = layer_state.create_group("G2", emit=False)
        layer_state.add_item("A", g1, 0, emit=False)
        layer_state.add_item("B", g2, 0, emit=False)

        cmd = RemoveMultipleItemsCommand(scene, [item1, item2], layer_state)
        cmd.execute()
        cmd.undo()

        assert layer_state.get_node(g1) is not None
        assert layer_state.get_node(g2) is not None
        assert layer_state.get_group_items_recursive(g1) == ["A"]
        assert layer_state.get_group_items_recursive(g2) == ["B"]


class TestNestedGroupsCascade:
    """Nested groups should cascade-delete when all children are gone."""

    def test_nested_empty_groups_both_deleted(self, layer_state):
        item = _make_item("A")
        scene = _make_scene([item])
        outer = layer_state.create_group("Outer", emit=False)
        inner = layer_state.create_group("Inner", parent_group_uuid=outer, emit=False)
        layer_state.add_item("A", inner, 0, emit=False)

        cmd = RemoveItemCommand(scene, item, layer_state)
        cmd.execute()

        assert layer_state.get_node(inner) is None
        assert layer_state.get_node(outer) is None

    def test_outer_group_kept_if_it_has_other_children(self, layer_state):
        item1 = _make_item("A")
        item2 = _make_item("B")
        scene = _make_scene([item1, item2])
        outer = layer_state.create_group("Outer", emit=False)
        inner = layer_state.create_group("Inner", parent_group_uuid=outer, emit=False)
        layer_state.add_item("A", inner, 0, emit=False)
        layer_state.add_item("B", outer, 0, emit=False)

        cmd = RemoveItemCommand(scene, item1, layer_state)
        cmd.execute()

        assert layer_state.get_node(inner) is None
        assert layer_state.get_node(outer) is not None
        assert layer_state.get_group_items_recursive(outer) == ["B"]

    def test_undo_restores_nested_groups(self, layer_state):
        item = _make_item("A")
        scene = _make_scene([item])
        outer = layer_state.create_group("Outer", emit=False)
        inner = layer_state.create_group("Inner", parent_group_uuid=outer, emit=False)
        layer_state.add_item("A", inner, 0, emit=False)

        cmd = RemoveItemCommand(scene, item, layer_state)
        cmd.execute()

        assert layer_state.get_node(outer) is None
        assert layer_state.get_node(inner) is None

        cmd.undo()

        assert layer_state.get_node(outer) is not None
        assert layer_state.get_node(outer).name == "Outer"
        assert layer_state.get_node(inner) is not None
        assert layer_state.get_node(inner).name == "Inner"
        assert layer_state.get_group_items_recursive(inner) == ["A"]
        inner_node = layer_state.get_node(inner)
        assert inner_node.parent is not None
        assert inner_node.parent.uuid == outer


class TestLinkedGroupsExcluded:
    """Linked assembly groups must NOT be auto-deleted even when empty."""

    def test_linked_group_kept_when_empty(self, layer_state):
        item = _make_item("A")
        scene = _make_scene([item])
        gid = layer_state.create_linked_group(
            "Linked",
            link_metadata=LinkMetadata(source_path="/some/path.json"),
            emit=False,
        )
        layer_state.add_item("A", gid, 0, emit=False)

        cmd = RemoveItemCommand(scene, item, layer_state)
        cmd.execute()

        assert layer_state.get_node(gid) is not None
        assert layer_state.get_node(gid).is_linked()
        assert layer_state.get_group_items_recursive(gid) == []

    def test_linked_group_kept_in_bulk_delete(self, layer_state):
        item1 = _make_item("A")
        item2 = _make_item("B")
        scene = _make_scene([item1, item2])
        gid = layer_state.create_linked_group(
            "Linked",
            link_metadata=LinkMetadata(source_path="/some/path.json"),
            emit=False,
        )
        layer_state.add_item("A", gid, 0, emit=False)
        layer_state.add_item("B", gid, 1, emit=False)

        cmd = RemoveMultipleItemsCommand(scene, [item1, item2], layer_state)
        cmd.execute()

        assert layer_state.get_node(gid) is not None
        assert layer_state.get_group_items_recursive(gid) == []

    def test_nonlinked_parent_of_linked_not_cascaded(self, layer_state):
        """A non-linked outer group should NOT be deleted if its only child is
        a linked group (even if that linked group is empty)."""
        item = _make_item("A")
        scene = _make_scene([item])
        outer = layer_state.create_group("Outer", emit=False)
        linked = layer_state.create_linked_group(
            "Linked",
            link_metadata=LinkMetadata(source_path="/x.json"),
            parent_group_uuid=outer,
            emit=False,
        )
        layer_state.add_item("A", linked, 0, emit=False)

        cmd = RemoveItemCommand(scene, item, layer_state)
        cmd.execute()

        # Linked group stays (it's linked)
        assert layer_state.get_node(linked) is not None
        # Outer stays too (it still has the linked child)
        assert layer_state.get_node(outer) is not None


class TestGroupPropertiesPreserved:
    """Undo should preserve group properties (collapsed, visible, locked)."""

    def test_group_properties_restored_on_undo(self, layer_state):
        item = _make_item("A")
        scene = _make_scene([item])
        gid = layer_state.create_group("Props", emit=False)
        layer_state.set_group_collapsed(gid, True, emit=False)
        layer_state.set_node_visible(gid, False, emit=False)
        layer_state.set_node_locked(gid, True, emit=False)
        layer_state.add_item("A", gid, 0, emit=False)

        cmd = RemoveItemCommand(scene, item, layer_state)
        cmd.execute()

        assert layer_state.get_node(gid) is None

        cmd.undo()

        node = layer_state.get_node(gid)
        assert node is not None
        assert node.collapsed is True
        assert node.visible is False
        assert node.locked is True
