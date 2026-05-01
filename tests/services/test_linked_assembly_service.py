"""Tests for LinkedAssemblyService and related data model changes."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from optiverse.core.exceptions import CircularLinkError
from optiverse.core.layer_tree_state import LayerTreeState, LinkMetadata
from optiverse.platform.paths import (
    make_assembly_relative,
    resolve_assembly_relative_path,
    set_current_assembly_dir,
)

# ---------------------------------------------------------------------------
# LinkMetadata
# ---------------------------------------------------------------------------


class TestLinkMetadata:
    def test_to_dict_round_trip(self):
        meta = LinkMetadata(
            source_path="@assembly/sub/test.json",
            offset_x=10.5,
            offset_y=-3.0,
            rotation_deg=45.0,
        )
        d = meta.to_dict()
        assert d["source_path"] == "@assembly/sub/test.json"
        assert d["offset_x"] == 10.5
        assert d["offset_y"] == -3.0
        assert d["rotation_deg"] == 45.0
        assert "editing" not in d

        restored = LinkMetadata.from_dict(d)
        assert restored.source_path == meta.source_path
        assert restored.offset_x == meta.offset_x
        assert restored.offset_y == meta.offset_y
        assert restored.rotation_deg == meta.rotation_deg
        assert restored.editing is False

    def test_defaults(self):
        meta = LinkMetadata(source_path="/tmp/test.json")
        assert meta.offset_x == 0.0
        assert meta.offset_y == 0.0
        assert meta.rotation_deg == 0.0
        assert meta.editing is False


# ---------------------------------------------------------------------------
# LayerTreeState with link_metadata
# ---------------------------------------------------------------------------


class TestLayerTreeStateLinked:
    def test_create_linked_group(self):
        st = LayerTreeState()
        meta = LinkMetadata(source_path="@assembly/sub.json", offset_x=10.0)
        gid = st.create_linked_group("🔗 Sub", meta, emit=False)

        node = st.get_node(gid)
        assert node is not None
        assert node.is_group()
        assert node.is_linked()
        assert node.link_metadata is not None
        assert node.link_metadata.source_path == "@assembly/sub.json"
        assert node.link_metadata.offset_x == 10.0

    def test_get_linked_groups(self):
        st = LayerTreeState()
        meta = LinkMetadata(source_path="a.json")
        st.create_linked_group("Link A", meta, emit=False)
        st.create_group("Regular Group", emit=False)
        meta2 = LinkMetadata(source_path="b.json")
        st.create_linked_group("Link B", meta2, emit=False)

        linked = st.get_linked_groups()
        assert len(linked) == 2
        names = {n.name for n in linked}
        assert names == {"Link A", "Link B"}

    def test_serialize_with_link_metadata(self):
        st = LayerTreeState()
        meta = LinkMetadata(
            source_path="@assembly/subsystem.json",
            offset_x=100.0,
            offset_y=50.0,
            rotation_deg=90.0,
        )
        gid = st.create_linked_group("🔗 Test", meta, emit=False)
        st.add_item("item-1", gid, emit=False)

        d = st.to_dict()
        assert d["version"] == 1

        nodes = d["nodes"]
        assert len(nodes) == 1
        group_node = nodes[0]
        assert group_node["type"] == "group"
        assert "link_metadata" in group_node
        lm = group_node["link_metadata"]
        assert lm["source_path"] == "@assembly/subsystem.json"
        assert lm["offset_x"] == 100.0
        assert lm["rotation_deg"] == 90.0

    def test_deserialize_with_link_metadata(self):
        data = {
            "version": 1,
            "nodes": [
                {
                    "uuid": "g1",
                    "type": "group",
                    "name": "🔗 Linked",
                    "link_metadata": {
                        "source_path": "@assembly/test.json",
                        "offset_x": 5.0,
                        "offset_y": 10.0,
                        "rotation_deg": 0.0,
                    },
                    "children": [
                        {"uuid": "i1", "type": "item"},
                    ],
                },
            ],
        }
        st = LayerTreeState.from_dict(data)
        node = st.get_node("g1")
        assert node is not None
        assert node.is_linked()
        assert node.link_metadata is not None
        assert node.link_metadata.source_path == "@assembly/test.json"
        assert node.link_metadata.offset_x == 5.0

        items = st.get_group_items_recursive("g1")
        assert items == ["i1"]

    def test_old_format_without_link_metadata(self):
        """Old layer_state without link_metadata should still load fine."""
        data = {
            "version": 1,
            "nodes": [
                {
                    "uuid": "g1",
                    "type": "group",
                    "name": "Regular Group",
                    "children": [{"uuid": "i1", "type": "item"}],
                },
            ],
        }
        st = LayerTreeState.from_dict(data)
        node = st.get_node("g1")
        assert node is not None
        assert not node.is_linked()
        assert node.link_metadata is None

    def test_is_linked_on_regular_items(self):
        st = LayerTreeState()
        st.add_item("item-1", emit=False)
        node = st.get_node("item-1")
        assert node is not None
        assert not node.is_linked()

    def test_round_trip_preserves_link_metadata(self):
        st = LayerTreeState()
        st.add_item("b", None, emit=False)
        meta = LinkMetadata(
            source_path="/abs/path.json", offset_x=1.0, offset_y=2.0, rotation_deg=3.0,
        )
        gid = st.create_linked_group("Test", meta, index=10**9, emit=False)
        st.add_item("a", gid, emit=False)

        d = st.to_dict()
        st2 = LayerTreeState.from_dict(d)

        assert st2.get_all_items_in_order() == ["b", "a"]
        node = st2.get_node(gid)
        assert node is not None
        assert node.is_linked()
        assert node.link_metadata.source_path == "/abs/path.json"
        assert node.link_metadata.offset_x == 1.0


# ---------------------------------------------------------------------------
# Assembly path resolution
# ---------------------------------------------------------------------------


class TestAssemblyPaths:
    def test_resolve_assembly_relative(self, tmp_path):
        target = tmp_path / "sub" / "test.json"
        target.parent.mkdir(parents=True)
        target.touch()

        result = resolve_assembly_relative_path("@assembly/sub/test.json", tmp_path)
        assert result is not None
        assert Path(result).name == "test.json"

    def test_resolve_with_module_level_dir(self, tmp_path):
        set_current_assembly_dir(tmp_path)
        try:
            target = tmp_path / "linked.json"
            target.touch()
            result = resolve_assembly_relative_path("@assembly/linked.json")
            assert result is not None
            assert Path(result).name == "linked.json"
        finally:
            set_current_assembly_dir(None)

    def test_resolve_returns_none_without_dir(self):
        set_current_assembly_dir(None)
        result = resolve_assembly_relative_path("@assembly/test.json")
        assert result is None

    def test_make_assembly_relative(self, tmp_path):
        abs_path = str(tmp_path / "sub" / "file.json")
        result = make_assembly_relative(abs_path, tmp_path)
        assert result == "@assembly/sub/file.json"

    def test_make_assembly_relative_outside(self, tmp_path):
        result = make_assembly_relative("/totally/different/path.json", tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# Deterministic UUID generation
# ---------------------------------------------------------------------------


class TestDeterministicUUIDs:
    def test_same_inputs_produce_same_uuid(self):
        from optiverse.services.linked_assembly_service import _instance_uuid

        u1 = _instance_uuid("link-abc", "item-123")
        u2 = _instance_uuid("link-abc", "item-123")
        assert u1 == u2

    def test_different_links_produce_different_uuids(self):
        from optiverse.services.linked_assembly_service import _instance_uuid

        u1 = _instance_uuid("link-abc", "item-123")
        u2 = _instance_uuid("link-xyz", "item-123")
        assert u1 != u2

    def test_different_items_produce_different_uuids(self):
        from optiverse.services.linked_assembly_service import _instance_uuid

        u1 = _instance_uuid("link-abc", "item-1")
        u2 = _instance_uuid("link-abc", "item-2")
        assert u1 != u2

    def test_produces_valid_uuid(self):
        from optiverse.services.linked_assembly_service import _instance_uuid

        result = _instance_uuid("link-abc", "item-123")
        parsed = uuid.UUID(result)
        assert parsed.version == 5


# ---------------------------------------------------------------------------
# Circular link detection
# ---------------------------------------------------------------------------


class TestCircularLinkDetection:
    def test_direct_self_reference(self, tmp_path):
        """A file that links back to the current assembly should be detected."""
        from optiverse.services.linked_assembly_service import LinkedAssemblyService

        main_file = tmp_path / "main.json"
        sub_file = tmp_path / "sub.json"

        sub_data = {
            "version": "2.0",
            "items": [],
            "layer_state": {
                "version": 1,
                "nodes": [
                    {
                        "uuid": "g1",
                        "type": "group",
                        "name": "back-link",
                        "link_metadata": {
                            "source_path": str(main_file),
                        },
                    },
                ],
            },
        }
        sub_file.write_text(json.dumps(sub_data))
        main_file.write_text(json.dumps({"version": "2.0", "items": []}))

        service = LinkedAssemblyService.__new__(LinkedAssemblyService)
        service._link_source_paths = {}

        forbidden = {main_file.resolve()}
        with pytest.raises(CircularLinkError):
            service._check_circular(sub_file, forbidden=forbidden)

    def test_no_circular_when_clean(self, tmp_path):
        from optiverse.services.linked_assembly_service import LinkedAssemblyService

        sub_file = tmp_path / "sub.json"
        sub_data = {"version": "2.0", "items": [], "layer_state": {"version": 1, "nodes": []}}
        sub_file.write_text(json.dumps(sub_data))

        service = LinkedAssemblyService.__new__(LinkedAssemblyService)
        service._link_source_paths = {}

        service._check_circular(sub_file)


# ---------------------------------------------------------------------------
# Cache fallback serialization
# ---------------------------------------------------------------------------


class TestCacheSerialization:
    def test_linked_assembly_cache_structure(self, tmp_path):
        """Verify the cache dict structure produced by the service."""
        from optiverse.services.linked_assembly_service import LinkedAssemblyService

        source = tmp_path / "sub.json"
        source_data = {"version": "2.0", "items": [{"_type": "source", "x": 0, "y": 0}]}
        source.write_text(json.dumps(source_data))

        service = LinkedAssemblyService.__new__(LinkedAssemblyService)
        service._link_source_paths = {"link-1": str(source)}
        service._link_caches = {
            "link-1": {
                "items": [{"_type": "source", "x": 0, "y": 0}],
                "_hash": "sha256:abc",
            },
        }
        service._link_items = {}

        cache = service.build_linked_assembly_cache()
        assert "link-1" in cache
        assert "source_hash" in cache["link-1"]
        assert "snapshot" in cache["link-1"]
        assert cache["link-1"]["snapshot"]["items"][0]["_type"] == "source"
