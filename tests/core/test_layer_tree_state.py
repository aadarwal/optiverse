from __future__ import annotations

from optiverse.core.layer_tree_state import LayerTreeState


class TestLayerTreeState:
    def test_create_group_and_add_items_order(self):
        st = LayerTreeState()
        g1 = st.create_group("G1", None, 0, emit=False)
        # Insert A after the group at root-level
        st.add_item("A", None, 1, emit=False)
        st.add_item("B", g1, 0, emit=False)
        st.add_item("C", g1, 1, emit=False)
        st.changed.emit()

        # Depth-first: groups traverse into items; roots preserve order of insertion
        assert st.get_all_items_in_order() == ["B", "C", "A"]

    def test_move_item_to_group_and_ungroup(self):
        st = LayerTreeState()
        g1 = st.create_group("G1", None, 0, emit=False)
        st.add_item("A", None, 0, emit=False)
        st.add_item("B", None, 1, emit=False)
        st.changed.emit()

        st.move_item_to_group("B", g1, emit=False)
        st.changed.emit()
        assert st.get_group_for_item("B") == g1
        assert st.get_group_items_recursive(g1) == ["B"]

        st.move_item_to_group("B", None, emit=False)
        st.changed.emit()
        assert st.get_group_for_item("B") is None

    def test_serialize_round_trip(self):
        st = LayerTreeState()
        g1 = st.create_group("G1", None, 0, emit=False)
        st.set_group_collapsed(g1, True, emit=False)
        st.add_item("A", g1, 0, emit=False)
        st.add_item("B", None, 0, emit=False)
        st.changed.emit()

        data = st.to_dict()
        st2 = LayerTreeState.from_dict(data)
        assert st2.to_dict() == data
        assert st2.get_all_items_in_order() == st.get_all_items_in_order()

    def test_legacy_migration_builds_expected_order(self):
        # Legacy groups format: list of dicts with
        # group_uuid/name/collapsed/item_uuids/parent_group_uuid
        groups = [
            {"group_uuid": "G", "name": "Group", "collapsed": False, "item_uuids": ["B"]},
        ]
        items_with_z = [(2.0, "A"), (1.0, "B"), (0.0, "C")]  # z desc => A, B, C
        st = LayerTreeState.from_legacy(groups, items_with_z)

        # Root group first (legacy behavior), then ungrouped items by z
        assert st.get_all_items_in_order() == ["B", "A", "C"]


