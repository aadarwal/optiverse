"""Service for managing linked assembly references.

Linked assemblies are external JSON files referenced by the main assembly.
Items are loaded from the source file at runtime and appear as locked groups.
A QFileSystemWatcher monitors source files and notifies on changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid as uuid_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6 import QtCore, QtWidgets

from ..core.exceptions import CircularLinkError, LinkedAssemblyLoadError
from ..core.layer_tree_state import LinkMetadata
from ..platform.paths import resolve_assembly_relative_path

if TYPE_CHECKING:
    from ..core.layer_tree_state import LayerTreeState as LayerTreeStateType
    from ..services.library_service import LibraryService
    from ..services.log_service import LogService

_logger = logging.getLogger(__name__)

LINKED_ASSEMBLY_NS = uuid_module.UUID("a3f1d8e0-7c2b-4f1a-b9d3-6e8f0a1c2d3e")

MAX_LINK_DEPTH = 5

WATCHER_DEBOUNCE_MS = 500


def _instance_uuid(link_uuid: str, source_item_uuid: str) -> str:
    """Deterministic UUID for an item instance within a specific link."""
    return str(uuid_module.uuid5(LINKED_ASSEMBLY_NS, f"{link_uuid}:{source_item_uuid}"))


def _file_hash(path: Path) -> str:
    """SHA-256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


class LinkedAssemblyService(QtCore.QObject):
    """Manages linked assembly references, file watching, and edit-in-context."""

    sourceFileChanged = QtCore.pyqtSignal(str, str)

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        layer_state: LayerTreeStateType,
        log_service: LogService,
        library_service: LibraryService | None = None,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent)
        self._scene = scene
        self._layer_state = layer_state
        self._log_service = log_service
        self._library_service = library_service

        self._watcher = QtCore.QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed_raw)

        self._debounce_timer = QtCore.QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._flush_pending_changes)
        self._pending_changed_paths: set[str] = set()

        # link_uuid -> list of instance UUIDs for items we own
        self._link_items: dict[str, list[str]] = {}
        # link_uuid -> absolute source path
        self._link_source_paths: dict[str, str] = {}
        # link_uuid -> cached snapshot dict (for serialization fallback)
        self._link_caches: dict[str, dict[str, Any]] = {}
        # Suppress watcher during our own writes
        self._suppress_paths: set[str] = set()
        # Path to the currently open main assembly (for circular detection)
        self._current_assembly_path: str | None = None
        # instance UUID -> original source UUID (for write-back stability)
        self._instance_to_source: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_link(
        self,
        source_path: str,
        assembly_dir: Path | None = None,
        link_uuid: str | None = None,
    ) -> str:
        """Register a new linked assembly and load its items.

        Returns the link group UUID.
        """
        abs_path = self._resolve_to_absolute(source_path, assembly_dir)
        if abs_path is None:
            raise LinkedAssemblyLoadError(source_path, "Cannot resolve path")

        forbidden: set[Path] = set()
        if self._current_assembly_path:
            forbidden.add(Path(self._current_assembly_path).resolve())
        self._check_circular(Path(abs_path), forbidden=forbidden)

        gid = link_uuid or str(uuid_module.uuid4())
        self._link_source_paths[gid] = abs_path
        self._link_items[gid] = []

        self._watch_path(abs_path)

        return gid

    def remove_link(self, link_uuid: str) -> None:
        """Remove a linked assembly: delete scene items, unwatch if needed."""
        self._remove_scene_items(link_uuid)
        abs_path = self._link_source_paths.pop(link_uuid, None)
        self._link_items.pop(link_uuid, None)
        self._link_caches.pop(link_uuid, None)

        if abs_path and not any(
            p == abs_path for u, p in self._link_source_paths.items()
        ):
            self._unwatch_path(abs_path)

    def load_link_items(
        self,
        link_uuid: str,
        connect_item_signals: Any | None = None,
    ) -> list[QtWidgets.QGraphicsItem]:
        """Load (or reload) items for a link from its source file.

        Returns list of QGraphicsItems added to the scene.
        """
        abs_path = self._link_source_paths.get(link_uuid)
        if not abs_path:
            return []

        data = self._try_load_source(abs_path, link_uuid)
        if data is None:
            return []

        self._update_cache(link_uuid, abs_path, data)
        return self._materialize_items(link_uuid, data, connect_item_signals)

    def reload_link(
        self,
        link_uuid: str,
        connect_item_signals: Any | None = None,
    ) -> list[QtWidgets.QGraphicsItem]:
        """Reload a linked assembly: remove old items, load fresh from source."""
        self._remove_scene_items(link_uuid)

        if self._layer_state:
            for uid in list(self._link_items.get(link_uuid, [])):
                self._layer_state.remove_item(uid, emit=False)
        self._link_items[link_uuid] = []

        return self.load_link_items(link_uuid, connect_item_signals)

    def reload_all_for_source(
        self,
        source_path: str,
        connect_item_signals: Any | None = None,
    ) -> None:
        """Reload all link instances that reference the given source file."""
        for gid, path in list(self._link_source_paths.items()):
            if path == source_path:
                self.reload_link(gid, connect_item_signals)

    def get_all_links_for_source(self, source_path: str) -> list[str]:
        return [gid for gid, p in self._link_source_paths.items() if p == source_path]

    def get_link_item_uuids(self, link_uuid: str) -> list[str]:
        return list(self._link_items.get(link_uuid, []))

    def get_all_linked_item_uuids(self) -> set[str]:
        """Return all item UUIDs owned by any linked assembly."""
        result: set[str] = set()
        for uuids in self._link_items.values():
            result.update(uuids)
        return result

    def get_cache(self, link_uuid: str) -> dict[str, Any] | None:
        return self._link_caches.get(link_uuid)

    def set_cache(self, link_uuid: str, cache: dict[str, Any]) -> None:
        self._link_caches[link_uuid] = cache

    def get_source_path(self, link_uuid: str) -> str | None:
        return self._link_source_paths.get(link_uuid)

    # ------------------------------------------------------------------
    # Edit-in-Context
    # ------------------------------------------------------------------

    def begin_edit_in_context(self, link_uuid: str) -> None:
        """Unlock items for in-place editing."""
        node = self._layer_state.get_node(link_uuid) if self._layer_state else None
        if node and node.link_metadata:
            node.link_metadata.editing = True

        for uid in self._link_items.get(link_uuid, []):
            item = self._find_scene_item(uid)
            if item:
                self._lock_item(item, is_editing=True)

    def end_edit_in_context(self, link_uuid: str, save: bool = True) -> bool:
        """Finish editing: write back to source and re-lock.

        Returns True if write-back succeeded.
        """
        node = self._layer_state.get_node(link_uuid) if self._layer_state else None
        meta = node.link_metadata if node else None
        if not meta:
            return False

        success = True
        if save:
            success = self._write_back_to_source(link_uuid, meta)

        meta.editing = False

        for uid in self._link_items.get(link_uuid, []):
            item = self._find_scene_item(uid)
            if item:
                self._lock_item(item, is_editing=False)

        return success

    def unlink_embed(self, link_uuid: str) -> None:
        """Convert a linked group into a regular group (break the link)."""
        node = self._layer_state.get_node(link_uuid) if self._layer_state else None
        if node:
            node.link_metadata = None

        owned_uuids = set(self._link_items.pop(link_uuid, []))
        abs_path = self._link_source_paths.pop(link_uuid, None)
        self._link_caches.pop(link_uuid, None)

        if abs_path and not any(
            p == abs_path for p in self._link_source_paths.values()
        ):
            self._unwatch_path(abs_path)

        for uid in owned_uuids:
            item = self._find_scene_item(uid)
            if item:
                self._lock_item(item, is_editing=True)

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def build_linked_assembly_cache(self) -> dict[str, Any]:
        """Return the ``linked_assembly_cache`` dict for the main assembly file."""
        cache: dict[str, Any] = {}
        for gid, snap in self._link_caches.items():
            cache[gid] = {
                "source_hash": snap.get("_hash", ""),
                "snapshot": snap,
            }
        return cache

    def restore_from_cache(
        self,
        link_uuid: str,
        cache_entry: dict[str, Any],
        source_path: str,
    ) -> None:
        """Restore link tracking state from a cached entry during load."""
        self._link_source_paths[link_uuid] = source_path
        self._link_items.setdefault(link_uuid, [])
        snapshot = cache_entry.get("snapshot", {})
        if snapshot:
            self._link_caches[link_uuid] = snapshot

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_to_absolute(
        self, source_path: str, assembly_dir: Path | None = None,
    ) -> str | None:
        if source_path.startswith("@assembly/"):
            return resolve_assembly_relative_path(source_path, assembly_dir)
        p = Path(source_path)
        if p.is_absolute():
            return str(p)
        if assembly_dir:
            return str((assembly_dir / source_path).resolve())
        return None

    def _check_circular(
        self, source_file: Path, forbidden: set[Path] | None = None, depth: int = 0,
    ) -> None:
        """Recursively check for circular links up to MAX_LINK_DEPTH.

        *forbidden* is the set of resolved paths that would form a cycle if
        encountered as a link target (starts with the current assembly + the
        source file itself).
        """
        if depth > MAX_LINK_DEPTH:
            return
        if not source_file.exists():
            return

        resolved = source_file.resolve()
        if forbidden is None:
            forbidden = set()
        forbidden = forbidden | {resolved}

        try:
            with open(source_file, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return

        layer_data = data.get("layer_state", {})
        for node_d in layer_data.get("nodes", []):
            self._check_node_circular(node_d, source_file.parent, forbidden, depth)

    def _check_node_circular(
        self, node_d: dict, parent_dir: Path, forbidden: set[Path], depth: int,
    ) -> None:
        lm = node_d.get("link_metadata")
        if lm:
            linked_path_str = self._resolve_to_absolute(lm["source_path"], parent_dir)
            if linked_path_str:
                linked_path = Path(linked_path_str).resolve()
                if linked_path in forbidden:
                    raise CircularLinkError(str(linked_path))
                self._check_circular(linked_path, forbidden, depth + 1)

        for child_d in node_d.get("children", []):
            self._check_node_circular(child_d, parent_dir, forbidden, depth)

    def _try_load_source(
        self, abs_path: str, link_uuid: str,
    ) -> dict[str, Any] | None:
        try:
            with open(abs_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _logger.warning("Failed to load linked source %s: %s", abs_path, e)
            cached = self._link_caches.get(link_uuid)
            if cached:
                self._log_service.warning(
                    f"Using cached snapshot for '{abs_path}' (source unavailable)",
                    "LinkedAssembly",
                )
                return cached
            self._log_service.error(
                f"Cannot load linked assembly '{abs_path}': {e}", "LinkedAssembly",
            )
            return None

    def _update_cache(
        self, link_uuid: str, abs_path: str, data: dict[str, Any],
    ) -> None:
        try:
            data_copy = {
                k: v for k, v in data.items()
                if k in ("items", "rulers", "texts", "rectangles", "path_measures", "layer_state")
            }
            data_copy["_hash"] = _file_hash(Path(abs_path))
            self._link_caches[link_uuid] = data_copy
        except OSError:
            pass

    def _materialize_items(
        self,
        link_uuid: str,
        data: dict[str, Any],
        connect_item_signals: Any | None = None,
    ) -> list[QtWidgets.QGraphicsItem]:
        """Deserialize items from data and add them to the scene as locked."""
        from ..objects import RectangleItem
        from ..objects.annotations import RulerItem, TextNoteItem
        from ..objects.type_registry import deserialize_item

        roots = self._library_service.get_all_roots() if self._library_service else None

        node = self._layer_state.get_node(link_uuid) if self._layer_state else None
        meta = node.link_metadata if node else None
        ox = meta.offset_x if meta else 0.0
        oy = meta.offset_y if meta else 0.0
        rot = meta.rotation_deg if meta else 0.0
        is_editing = meta.editing if meta else False

        items: list[QtWidgets.QGraphicsItem] = []

        for item_data in data.get("items", []):
            try:
                item = deserialize_item(item_data, library_roots=roots)
                if item is None:
                    continue
                source_uuid = str(getattr(item, "item_uuid", ""))
                inst_uuid = _instance_uuid(link_uuid, source_uuid)
                item.item_uuid = inst_uuid  # type: ignore[attr-defined]
                self._instance_to_source[inst_uuid] = source_uuid
                self._apply_transform(item, ox, oy, rot)
                if hasattr(item, "_sync_params_from_item"):
                    item._sync_params_from_item()
                self._lock_item(item, is_editing)
                self._scene.addItem(item)
                if connect_item_signals:
                    connect_item_signals(item)
                self._link_items.setdefault(link_uuid, []).append(inst_uuid)
                items.append(item)
            except (KeyError, ValueError, TypeError) as e:
                _logger.debug("Error materializing linked item: %s", e)

        for ruler_data in data.get("rulers", []):
            try:
                ruler = RulerItem.from_dict(ruler_data)
                source_uuid = str(getattr(ruler, "item_uuid", ""))
                inst_uuid = _instance_uuid(link_uuid, source_uuid)
                ruler.item_uuid = inst_uuid  # type: ignore[attr-defined]
                self._instance_to_source[inst_uuid] = source_uuid
                self._apply_transform(ruler, ox, oy, rot)
                self._lock_item(ruler, is_editing)
                self._scene.addItem(ruler)
                if connect_item_signals:
                    connect_item_signals(ruler)
                self._link_items.setdefault(link_uuid, []).append(inst_uuid)
                items.append(ruler)
            except (KeyError, ValueError, TypeError) as e:
                _logger.debug("Error materializing linked ruler: %s", e)

        for text_data in data.get("texts", []):
            try:
                note = TextNoteItem.from_dict(text_data)
                source_uuid = str(getattr(note, "item_uuid", ""))
                inst_uuid = _instance_uuid(link_uuid, source_uuid)
                note.item_uuid = inst_uuid  # type: ignore[attr-defined]
                self._instance_to_source[inst_uuid] = source_uuid
                self._apply_transform(note, ox, oy, rot)
                self._lock_item(note, is_editing)
                self._scene.addItem(note)
                if connect_item_signals:
                    connect_item_signals(note)
                self._link_items.setdefault(link_uuid, []).append(inst_uuid)
                items.append(note)
            except (KeyError, ValueError, TypeError) as e:
                _logger.debug("Error materializing linked text: %s", e)

        for rect_data in data.get("rectangles", []):
            try:
                rect = RectangleItem.from_dict(rect_data)
                source_uuid = str(getattr(rect, "item_uuid", ""))
                inst_uuid = _instance_uuid(link_uuid, source_uuid)
                rect.item_uuid = inst_uuid  # type: ignore[attr-defined]
                self._instance_to_source[inst_uuid] = source_uuid
                self._apply_transform(rect, ox, oy, rot)
                self._lock_item(rect, is_editing)
                self._scene.addItem(rect)
                if connect_item_signals:
                    connect_item_signals(rect)
                self._link_items.setdefault(link_uuid, []).append(inst_uuid)
                items.append(rect)
            except (KeyError, ValueError, TypeError) as e:
                _logger.debug("Error materializing linked rectangle: %s", e)

        pm_list = data.get("path_measures", [])
        if pm_list:
            _logger.warning(
                "Linked assembly contains %d path measure(s) which require "
                "ray data and cannot be materialized in a linked context — skipped.",
                len(pm_list),
            )

        if self._layer_state:
            for item in items:
                uid = getattr(item, "item_uuid", None)
                if uid:
                    self._layer_state.add_item(uid, link_uuid, index=10**9, emit=False)
            self._layer_state.changed.emit()

        return items

    @staticmethod
    def _apply_transform(
        item: QtWidgets.QGraphicsItem,
        offset_x: float,
        offset_y: float,
        rotation_deg: float,
    ) -> None:
        """Apply instance offset + rotation to a deserialized item."""
        if rotation_deg != 0.0:
            cos_r = math.cos(math.radians(rotation_deg))
            sin_r = math.sin(math.radians(rotation_deg))
            x, y = item.x(), item.y()
            rx = x * cos_r - y * sin_r
            ry = x * sin_r + y * cos_r
            item.setPos(rx + offset_x, ry + offset_y)
            item.setRotation(item.rotation() + rotation_deg)
        else:
            item.setPos(item.x() + offset_x, item.y() + offset_y)

    @staticmethod
    def _lock_item(item: QtWidgets.QGraphicsItem, is_editing: bool = False) -> None:
        """Set linked-item interaction state via Qt flags and opacity.

        This is intentionally separate from the user-facing set_locked()
        mechanism -- linked-lock is a structural property of the reference,
        not a user-togglable padlock.
        """
        if is_editing:
            item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            item.setOpacity(1.0)
        else:
            item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
            item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            item.setOpacity(0.85)

    def _restore_source_uuid(self, d: dict[str, Any], inst_uuid: str) -> None:
        """Replace instance UUID in a serialized dict with the original source UUID."""
        source_uuid = self._instance_to_source.get(inst_uuid)
        if source_uuid and "item_uuid" in d:
            d["item_uuid"] = source_uuid

    def _remove_scene_items(self, link_uuid: str) -> None:
        for uid in self._link_items.get(link_uuid, []):
            item = self._find_scene_item(uid)
            if item:
                self._scene.removeItem(item)

    def _find_scene_item(self, item_uuid: str) -> QtWidgets.QGraphicsItem | None:
        for item in self._scene.items():
            if getattr(item, "item_uuid", None) == item_uuid:
                return item
        return None

    def _write_back_to_source(self, link_uuid: str, meta: LinkMetadata) -> bool:
        """Serialize current link items back to the source file."""
        from ..core.protocols import Serializable
        from ..objects import BaseObj, RectangleItem
        from ..objects.annotations import RulerItem, TextNoteItem

        abs_path = self._link_source_paths.get(link_uuid)
        if not abs_path:
            return False

        # Read existing source to preserve structure we don't edit
        try:
            with open(abs_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {"version": "2.0"}

        # Replace only the item lists (our edits); preserve everything else
        data["items"] = []
        data["rulers"] = []
        data["texts"] = []
        data["rectangles"] = []

        ox, oy, rot = meta.offset_x, meta.offset_y, meta.rotation_deg

        for uid in self._link_items.get(link_uuid, []):
            item = self._find_scene_item(uid)
            if item is None:
                continue

            if isinstance(item, BaseObj) and isinstance(item, Serializable):
                d = item.to_dict()
                self._restore_source_uuid(d, uid)
                self._reverse_transform_optical(d, ox, oy, rot)
                data["items"].append(d)
            elif isinstance(item, RulerItem):
                d = item.to_dict()
                self._restore_source_uuid(d, uid)
                self._reverse_transform_ruler(d, ox, oy, rot)
                data["rulers"].append(d)
            elif isinstance(item, TextNoteItem):
                d = item.to_dict()
                self._restore_source_uuid(d, uid)
                self._reverse_transform_text(d, ox, oy, rot)
                data["texts"].append(d)
            elif isinstance(item, RectangleItem):
                d = item.to_dict()
                self._restore_source_uuid(d, uid)
                self._reverse_transform_rectangle(d, ox, oy, rot)
                data["rectangles"].append(d)

        self._suppress_paths.add(abs_path)
        try:
            with open(abs_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self._log_service.info(
                f"Wrote changes back to '{abs_path}'", "LinkedAssembly",
            )
            return True
        except OSError as e:
            self._log_service.error(
                f"Failed to write back to '{abs_path}': {e}", "LinkedAssembly",
            )
            return False
        finally:
            QtCore.QTimer.singleShot(
                WATCHER_DEBOUNCE_MS + 200,
                lambda p=abs_path: self._suppress_paths.discard(p),
            )

    @staticmethod
    def _reverse_pos(x: float, y: float, ox: float, oy: float, rot: float) -> tuple[float, float]:
        """Subtract offset then apply inverse rotation to get source-local position."""
        x -= ox
        y -= oy
        if rot != 0.0:
            cos_r = math.cos(math.radians(-rot))
            sin_r = math.sin(math.radians(-rot))
            x, y = x * cos_r - y * sin_r, x * sin_r + y * cos_r
        return x, y

    @staticmethod
    def _reverse_transform_optical(
        d: dict[str, Any], ox: float, oy: float, rot: float,
    ) -> None:
        """Reverse instance transform for optical items (x_mm/y_mm/angle_deg).

        ``angle_deg`` uses user convention (CW); Qt rotation = -angle_deg.
        Forward added ``rot`` to Qt rotation, so reversing adds ``rot`` to
        user angle (they are negations).
        """
        x, y = d.get("x_mm", 0.0), d.get("y_mm", 0.0)
        x, y = LinkedAssemblyService._reverse_pos(x, y, ox, oy, rot)
        d["x_mm"] = x
        d["y_mm"] = y
        if rot != 0.0:
            d["angle_deg"] = (d.get("angle_deg", 0.0) + rot) % 360

    @staticmethod
    def _reverse_transform_ruler(
        d: dict[str, Any], ox: float, oy: float, rot: float,
    ) -> None:
        """Reverse instance transform for rulers (scene-space points list)."""
        points = d.get("points")
        if not points:
            return
        d["points"] = [
            list(LinkedAssemblyService._reverse_pos(p[0], p[1], ox, oy, rot))
            for p in points
        ]

    @staticmethod
    def _reverse_transform_text(
        d: dict[str, Any], ox: float, oy: float, rot: float,
    ) -> None:
        """Reverse instance transform for text notes (x/y, no rotation)."""
        x, y = d.get("x", 0.0), d.get("y", 0.0)
        x, y = LinkedAssemblyService._reverse_pos(x, y, ox, oy, rot)
        d["x"] = x
        d["y"] = y

    @staticmethod
    def _reverse_transform_rectangle(
        d: dict[str, Any], ox: float, oy: float, rot: float,
    ) -> None:
        """Reverse instance transform for rectangles (x/y/angle_deg).

        Rectangle ``angle_deg`` is raw Qt rotation (not user convention).
        Forward added ``rot`` to Qt rotation, so reverse subtracts it.
        """
        x, y = d.get("x", 0.0), d.get("y", 0.0)
        x, y = LinkedAssemblyService._reverse_pos(x, y, ox, oy, rot)
        d["x"] = x
        d["y"] = y
        if rot != 0.0:
            d["angle_deg"] = d.get("angle_deg", 0.0) - rot

    # ------------------------------------------------------------------
    # File watching
    # ------------------------------------------------------------------

    def _watch_path(self, abs_path: str) -> None:
        watched = self._watcher.files()
        if abs_path not in watched:
            self._watcher.addPath(abs_path)

    def _unwatch_path(self, abs_path: str) -> None:
        if abs_path in self._watcher.files():
            self._watcher.removePath(abs_path)

    def _on_file_changed_raw(self, path: str) -> None:
        if path in self._suppress_paths:
            return
        self._pending_changed_paths.add(path)
        self._debounce_timer.start(WATCHER_DEBOUNCE_MS)

        if path not in self._watcher.files():
            self._watcher.addPath(path)

    def _flush_pending_changes(self) -> None:
        paths = list(self._pending_changed_paths)
        self._pending_changed_paths.clear()
        for path in paths:
            for gid in self.get_all_links_for_source(path):
                self.sourceFileChanged.emit(gid, path)

    def cleanup(self) -> None:
        """Remove all watches and timers."""
        self._debounce_timer.stop()
        for path in list(self._watcher.files()):
            self._watcher.removePath(path)

    def reset(self) -> None:
        """Full reset: remove watches and clear all internal state."""
        self.cleanup()
        self._link_source_paths.clear()
        self._link_items.clear()
        self._link_caches.clear()
        self._pending_changed_paths.clear()
        self._suppress_paths.clear()
        self._instance_to_source.clear()
        self._current_assembly_path = None
