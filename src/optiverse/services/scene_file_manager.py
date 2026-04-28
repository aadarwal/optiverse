"""
Scene file management for save, load, and autosave operations.

This module extracts file management logic from MainWindow to improve
code organization and reduce the MainWindow's size.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PyQt6 import QtWidgets

from ..core.exceptions import AssemblyLoadError, AssemblySaveError
from ..core.protocols import Serializable

if TYPE_CHECKING:
    from ..core.layer_tree_state import LayerTreeState
    from .linked_assembly_service import LinkedAssemblyService
    from .log_service import LogService


class SceneFileManager:
    """
    Manages scene file operations including save, load, and autosave.

    This class encapsulates all file-related operations to keep MainWindow focused
    on UI coordination rather than file management details.
    """

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        log_service: LogService,
        get_ray_data: Callable,
        on_modified: Callable[[bool], None],
        parent_widget: QtWidgets.QWidget,
        connect_item_signals: Callable | None = None,
        get_library_roots: Callable[[], list] | None = None,
    ):
        """
        Initialize the scene file manager.

        Args:
            scene: The graphics scene to save/load
            log_service: Logging service for errors and debug info
            get_ray_data: Callable to get current ray data (for path measures)
            on_modified: Callback when modified state changes
            parent_widget: Parent widget for dialogs
            connect_item_signals: Optional callback to connect signals for items
            get_library_roots: Callable returning current library root paths
        """
        self.scene = scene
        self.log_service = log_service
        self._get_ray_data = get_ray_data
        self._on_modified = on_modified
        self.parent_widget = parent_widget
        self._connect_item_signals = connect_item_signals
        self._get_library_roots = get_library_roots

        # File state
        self._saved_file_path: str | None = None
        self._autosave_path: str | None = None
        self._unsaved_id: str | None = None
        self._is_modified = False
        self._layer_state: LayerTreeState | None = None
        self._linked_assembly_service: LinkedAssemblyService | None = None

    def set_layer_state(self, layer_state: LayerTreeState) -> None:
        """Set the authoritative layer state for saving/loading layer hierarchy/order."""
        self._layer_state = layer_state

    def set_linked_assembly_service(self, service: LinkedAssemblyService) -> None:
        """Set the linked assembly service for save/load integration."""
        self._linked_assembly_service = service

    @property
    def saved_file_path(self) -> str | None:
        """Get the current saved file path."""
        return self._saved_file_path

    @saved_file_path.setter
    def saved_file_path(self, value: str | None):
        """Set the saved file path."""
        self._saved_file_path = value

    @property
    def is_modified(self) -> bool:
        """Check if the scene has unsaved modifications."""
        return self._is_modified

    def mark_modified(self):
        """Mark the scene as having unsaved changes."""
        if not self._is_modified:
            self._is_modified = True
            self._on_modified(True)

    def mark_clean(self):
        """Mark the scene as saved (no unsaved changes)."""
        if self._is_modified:
            self._is_modified = False
        self._on_modified(False)

    def get_autosave_path(self) -> str:
        """Get autosave path in AppData (safe from permission/sync issues)."""
        from ..platform.paths import _app_data_root

        autosave_dir = _app_data_root() / "autosave"
        autosave_dir.mkdir(parents=True, exist_ok=True)

        if self._saved_file_path:
            # Hash the absolute path to create unique filename
            path_hash = hashlib.md5(self._saved_file_path.encode()).hexdigest()[:12]
            base_name = os.path.splitext(os.path.basename(self._saved_file_path))[0]
            filename = f"{base_name}_{path_hash}.autosave.json"
        else:
            # For unsaved files: use timestamp + sequential ID
            if not self._unsaved_id:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                self._unsaved_id = f"untitled_{timestamp}"
            filename = f"{self._unsaved_id}.autosave.json"

        return str(autosave_dir / filename)

    def serialize_scene(self) -> dict:
        """Serialize scene to dictionary format."""
        from optiverse.objects.annotations.path_measure_item import PathMeasureItem

        from ..objects import BaseObj, RectangleItem
        from ..objects.annotations import RulerItem, TextNoteItem

        linked_uuids = (
            self._linked_assembly_service.get_all_linked_item_uuids()
            if self._linked_assembly_service
            else set()
        )

        data: dict[str, Any] = {
            "version": "2.0",
            "items": [],  # type: ignore[assignment]
            "rulers": [],  # type: ignore[assignment]
            "texts": [],  # type: ignore[assignment]
            "rectangles": [],  # type: ignore[assignment]
            "path_measures": [],  # type: ignore[assignment]
            "layer_state": {},  # type: ignore[assignment]
        }

        for it in self.scene.items():
            uid = getattr(it, "item_uuid", None)
            if uid and str(uid) in linked_uuids:
                continue
            if isinstance(it, BaseObj) and isinstance(it, Serializable):
                data["items"].append(it.to_dict())
            elif isinstance(it, RulerItem):
                data["rulers"].append(it.to_dict())
            elif isinstance(it, TextNoteItem):
                data["texts"].append(it.to_dict())
            elif isinstance(it, RectangleItem):
                data["rectangles"].append(it.to_dict())
            elif isinstance(it, PathMeasureItem):
                data["path_measures"].append(it.to_dict())

        # Convert absolute source paths to @assembly/ relative BEFORE to_dict()
        original_paths: dict[str, str] = {}
        if self._saved_file_path and self._layer_state:
            from pathlib import Path

            from ..platform.paths import make_assembly_relative

            assembly_dir = Path(self._saved_file_path).parent
            for node in self._layer_state.get_linked_groups():
                meta = node.link_metadata
                if meta and not meta.source_path.startswith("@assembly/"):
                    rel = make_assembly_relative(meta.source_path, assembly_dir)
                    if rel:
                        original_paths[node.uuid] = meta.source_path
                        meta.source_path = rel

        # Serialize layer state (single source of truth)
        if self._layer_state:
            data["layer_state"] = self._layer_state.to_dict()

        # Restore original absolute paths so in-memory state is unchanged
        if self._layer_state:
            for node in self._layer_state.get_linked_groups():
                if node.uuid in original_paths and node.link_metadata:
                    node.link_metadata.source_path = original_paths[node.uuid]

        # Include linked assembly cache for offline resilience
        if self._linked_assembly_service:
            cache = self._linked_assembly_service.build_linked_assembly_cache()
            if cache:
                data["linked_assembly_cache"] = cache

        return data

    def serialize_selected(self, uuids: set[str]) -> dict:
        """Serialize only the scene items whose *item_uuid* is in *uuids*."""
        from optiverse.objects.annotations.path_measure_item import PathMeasureItem

        from ..objects import BaseObj, RectangleItem
        from ..objects.annotations import RulerItem, TextNoteItem

        data: dict[str, Any] = {
            "version": "2.0",
            "items": [],
            "rulers": [],
            "texts": [],
            "rectangles": [],
            "path_measures": [],
            "layer_state": {},
        }

        for it in self.scene.items():
            uid = getattr(it, "item_uuid", None)
            if uid is None or str(uid) not in uuids:
                continue
            if isinstance(it, BaseObj) and isinstance(it, Serializable):
                data["items"].append(it.to_dict())
            elif isinstance(it, RulerItem):
                data["rulers"].append(it.to_dict())
            elif isinstance(it, TextNoteItem):
                data["texts"].append(it.to_dict())
            elif isinstance(it, RectangleItem):
                data["rectangles"].append(it.to_dict())
            elif isinstance(it, PathMeasureItem):
                data["path_measures"].append(it.to_dict())

        if self._layer_state:
            data["layer_state"] = self._layer_state.pruned_to_dict(uuids)

        return data

    def do_autosave(self):
        """Perform autosave to temporary file."""
        if not self._is_modified:
            return

        try:
            autosave_path = self.get_autosave_path()

            # Serialize scene
            data = self.serialize_scene()

            # Add metadata for recovery UI
            data["_autosave_meta"] = {
                "timestamp": datetime.datetime.now().isoformat(),
                "original_path": self._saved_file_path,
                "version": "2.0",
            }

            # Atomic write: temp file + rename
            autosave_dir = os.path.dirname(autosave_path)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=autosave_dir, delete=False, suffix=".tmp"
            ) as tmp:
                json.dump(data, tmp, indent=2)
                tmp_path = tmp.name

            # Atomic rename (overwrites existing autosave)
            os.replace(tmp_path, autosave_path)
            self._autosave_path = autosave_path

            self.log_service.debug(f"Autosaved to {autosave_path}", "Autosave")

        except (OSError, TypeError) as e:
            # OSError for file operations, TypeError for JSON serialization issues
            self.log_service.error(f"Autosave failed: {e}", "Autosave")

    def clear_autosave(self):
        """Delete autosave file."""
        try:
            if self._autosave_path and os.path.exists(self._autosave_path):
                os.unlink(self._autosave_path)
                self._autosave_path = None
                self.log_service.debug("Cleared autosave file", "Autosave")
        except OSError as e:
            self.log_service.error(f"Failed to clear autosave: {e}", "Autosave")

    def load_from_data(self, data: dict, library_roots: list | None = None) -> bool:
        """Load scene from data dict.

        Args:
            data: Scene data dictionary.
            library_roots: Pre-computed library root paths for resolving
                component image URIs.  Obtain via
                ``LibraryService.get_all_roots()``.

        Returns:
            True if legacy migration occurred (so caller can mark modified), else False.
        """
        from optiverse.objects.annotations.path_measure_item import PathMeasureItem

        from ..core.layer_tree_state import LayerTreeState
        from ..objects import BaseObj, RectangleItem
        from ..objects.annotations import RulerItem, TextNoteItem
        from ..objects.type_registry import deserialize_item

        # Clear scene
        for it in list(self.scene.items()):
            if isinstance(it, (BaseObj, RulerItem, TextNoteItem, RectangleItem)):
                self.scene.removeItem(it)

        # Clear layer state
        if self._layer_state:
            self._layer_state.clear(emit=False)

        # Load items — track failures for post-load report
        failed_items: list[str] = []
        for item_data in data.get("items", []):
            try:
                item = deserialize_item(item_data, library_roots=library_roots)
                if item is None:
                    failed_items.append(item_data.get("_type", "<unknown>"))
                    continue
                self.scene.addItem(item)
                if self._connect_item_signals:
                    self._connect_item_signals(item)
            except (KeyError, ValueError, TypeError) as e:
                self.log_service.error(f"Error loading item: {e}", "Load")
                failed_items.append(item_data.get("_type", "<unknown>"))

        # Load annotations
        for ruler_data in data.get("rulers", []):
            ruler = RulerItem.from_dict(ruler_data)
            if self._connect_item_signals:
                self._connect_item_signals(ruler)
            self.scene.addItem(ruler)

        for text_data in data.get("texts", []):
            note = TextNoteItem.from_dict(text_data)
            self.scene.addItem(note)
            if self._connect_item_signals:
                self._connect_item_signals(note)

        for rect_data in data.get("rectangles", []):
            rect = RectangleItem.from_dict(rect_data)
            self.scene.addItem(rect)
            if self._connect_item_signals:
                self._connect_item_signals(rect)

        # Load path measures
        ray_data = self._get_ray_data()
        for pm_data in data.get("path_measures", []):
            try:
                item = PathMeasureItem.from_dict(pm_data, ray_data)
                self.scene.addItem(item)
                if self._connect_item_signals:
                    self._connect_item_signals(item)
            except (KeyError, ValueError, TypeError) as e:
                # KeyError: missing required fields, ValueError/TypeError: invalid data
                self.log_service.error(f"Error loading path measure: {e}", "Load")

        # Build ordering input for legacy migration from scene z-values
        items_with_z: list[tuple[float, str]] = []
        for it in self.scene.items():
            if hasattr(it, "item_uuid") and hasattr(it, "type_name"):
                items_with_z.append((float(it.zValue()), str(it.item_uuid)))

        migrated = False
        if self._layer_state:
            if "layer_state" in data:
                tmp = LayerTreeState.from_dict(data.get("layer_state", {}))
                self._layer_state.replace_from(tmp, emit=True)
            elif "groups" in data:
                # One-way legacy migration
                tmp = LayerTreeState.from_legacy(data.get("groups", []) or [], items_with_z)
                self._layer_state.replace_from(tmp, emit=True)
                migrated = True
            else:
                # No layer info; still establish a stable ordering from z-values
                tmp = LayerTreeState.from_legacy([], items_with_z)
                self._layer_state.replace_from(tmp, emit=True)

        if failed_items:
            summary = ", ".join(failed_items[:10])
            if len(failed_items) > 10:
                summary += f" … and {len(failed_items) - 10} more"
            self.log_service.warning(
                f"{len(failed_items)} item(s) could not be loaded: {summary}", "Load",
            )
            QtWidgets.QMessageBox.warning(
                self.parent_widget,
                "Missing Components",
                f"{len(failed_items)} component(s) could not be loaded.\n\n"
                f"Types: {summary}\n\n"
                "The components may belong to a library that is not currently configured. "
                "You can add library paths in Preferences → Component Libraries.",
            )

        # Load linked assemblies
        if self._linked_assembly_service and self._layer_state:
            from pathlib import Path as _Path

            assembly_dir = _Path(self._saved_file_path).parent if self._saved_file_path else None
            cache_data = data.get("linked_assembly_cache", {})

            for node in self._layer_state.get_linked_groups():
                meta = node.link_metadata
                if not meta:
                    continue

                abs_path = None
                if meta.source_path.startswith("@assembly/"):
                    from ..platform.paths import resolve_assembly_relative_path
                    abs_path = resolve_assembly_relative_path(meta.source_path, assembly_dir)
                elif _Path(meta.source_path).is_absolute():
                    abs_path = meta.source_path

                if abs_path:
                    meta.source_path = abs_path

                cache_entry = cache_data.get(node.uuid, {})
                if cache_entry:
                    self._linked_assembly_service.restore_from_cache(
                        node.uuid, cache_entry, abs_path or meta.source_path,
                    )

                try:
                    self._linked_assembly_service.add_link(
                        abs_path or meta.source_path,
                        assembly_dir=assembly_dir,
                        link_uuid=node.uuid,
                    )
                    self._linked_assembly_service.load_link_items(
                        node.uuid, self._connect_item_signals,
                    )
                except Exception as e:
                    self.log_service.error(
                        f"Failed to load linked assembly '{meta.source_path}': {e}",
                        "Load",
                    )

        return migrated

    def _format_time_ago(self, delta: datetime.timedelta) -> str:
        """Format timedelta as human-readable string."""
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        elif seconds < 3600:
            return f"{seconds // 60}m ago"
        elif seconds < 86400:
            return f"{seconds // 3600}h ago"
        else:
            return f"{seconds // 86400}d ago"

    def check_autosave_recovery(self) -> bool:
        """
        Check for autosave on startup and offer recovery.

        Returns:
            True if recovery was performed, False otherwise
        """
        import os

        # Skip autosave recovery in headless environments (CI, tests) to avoid dialog hangs
        qpa_platform = os.environ.get("QT_QPA_PLATFORM", "").lower()
        if qpa_platform in ("offscreen", "minimal", "vnc"):
            return False

        from ..platform.paths import _app_data_root

        autosave_dir = _app_data_root() / "autosave"
        if not autosave_dir.exists():
            return False

        autosave_files = sorted(
            autosave_dir.glob("*.autosave.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )

        if not autosave_files:
            return False

        most_recent = autosave_files[0]

        try:
            with open(most_recent, encoding="utf-8") as f:
                data = json.load(f)

            if data.get("version") != "2.0":
                raise ValueError("Incompatible autosave version")

            meta = data.get("_autosave_meta", {})
            timestamp_str = meta.get("timestamp", "")
            original_path = meta.get("original_path")

            try:
                timestamp = datetime.datetime.fromisoformat(timestamp_str)
                age = datetime.datetime.now() - timestamp
                time_str = self._format_time_ago(age)
            except (ValueError, OSError):
                time_str = "unknown time"

            if original_path:
                file_name = os.path.basename(original_path)
                msg = f"Found autosave of '{file_name}'\nSaved: {time_str}"
            else:
                msg = f"Found autosave of unsaved file\nSaved: {time_str}"

            # Import here to avoid circular import
            from ..ui.theme_manager import question as theme_aware_question

            reply = theme_aware_question(
                self.parent_widget,
                "Recover Autosave?",
                f"{msg}\n\nWould you like to recover it?",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.Yes,
            )

            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                roots = self._get_library_roots() if self._get_library_roots else None
                self.load_from_data(data, library_roots=roots)
                self._saved_file_path = original_path
                self._autosave_path = str(most_recent)
                self.mark_modified()

                QtWidgets.QMessageBox.information(
                    self.parent_widget,
                    "Recovery Successful",
                    "Autosave recovered. Please save your work.",
                )
                return True
            else:
                most_recent.unlink()

        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            # OSError: file access, JSONDecodeError: corrupt file
            # KeyError/ValueError: invalid data structure
            self.log_service.error(f"Failed to recover autosave: {e}", "Recovery")

        return False

    def save_to_file(self, path: str) -> bool:
        """
        Save scene to specified file path.

        Returns:
            True if save was successful

        Raises:
            AssemblySaveError: If the file cannot be saved
        """
        data = self.serialize_scene()

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            self._saved_file_path = path
            if self._linked_assembly_service:
                self._linked_assembly_service._current_assembly_path = path
            self.mark_clean()
            self.clear_autosave()
            return True

        except (OSError, json.JSONDecodeError) as e:
            raise AssemblySaveError(path, str(e)) from e

    def open_file(self, path: str) -> bool:
        """
        Open and load a scene file.

        Returns:
            True if open was successful

        Raises:
            AssemblyLoadError: If the file cannot be opened or parsed
        """
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise AssemblyLoadError(path, str(e)) from e

        # Set assembly directory context for @assembly/ path resolution
        from pathlib import Path as _Path

        from ..platform.paths import set_current_assembly_dir

        set_current_assembly_dir(_Path(path).parent)

        if self._linked_assembly_service:
            self._linked_assembly_service._current_assembly_path = path

        self._saved_file_path = path
        roots = self._get_library_roots() if self._get_library_roots else None
        migrated = self.load_from_data(data, library_roots=roots)
        self._unsaved_id = None
        if migrated:
            self.mark_modified()
        else:
            self.mark_clean()
        return True

    def prompt_save_changes(self) -> QtWidgets.QMessageBox.StandardButton:
        """
        Prompt user to save unsaved changes.

        Returns:
            The user's choice (Save, Discard, or Cancel)
        """
        # Import here to avoid circular import
        from ..ui.theme_manager import question as theme_aware_question

        return theme_aware_question(
            self.parent_widget,
            "Unsaved Changes",
            "Do you want to save your changes before closing?",
            QtWidgets.QMessageBox.StandardButton.Save
            | QtWidgets.QMessageBox.StandardButton.Discard
            | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Save,
        )
