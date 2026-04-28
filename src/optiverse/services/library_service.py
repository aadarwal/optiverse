"""
Library service -- single source of truth for all component library locations.

Replaces the scattered ``get_all_custom_library_roots`` / ``get_all_library_roots``
calls with a centralized, cached, signal-emitting service that every consumer
injects once and never has to worry about passing the right arguments.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6 import QtCore

from ..platform.paths import (
    get_all_custom_library_roots,
    get_builtin_library_root,
    get_user_library_root,
)

if TYPE_CHECKING:
    from .settings_service import SettingsService

_logger = logging.getLogger(__name__)


@dataclass
class LibraryInfo:
    """Metadata for a single component library directory."""

    path: Path
    name: str
    source_type: str  # "builtin" | "user_default" | "scanned" | "settings"
    writable: bool = True
    component_count: int = 0
    exists: bool = True
    enabled: bool = True


class LibraryService(QtCore.QObject):
    """
    Owns the authoritative list of component libraries.

    Created once in ``MainWindow`` and injected into every subsystem that needs
    to know about libraries (dock, editor, scene loader, collaboration, ...).

    Emits *libraries_changed* whenever the list is rebuilt so that consumers
    (e.g. the library dock) can refresh automatically.
    """

    libraries_changed = QtCore.pyqtSignal()

    def __init__(self, settings_service: SettingsService, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._settings = settings_service
        self._libraries: list[LibraryInfo] = []
        self.refresh()

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def get_all(self) -> list[LibraryInfo]:
        """Return every known library (builtin + user + scanned + settings)."""
        return list(self._libraries)

    def get_writable(self) -> list[LibraryInfo]:
        """Return only enabled libraries that the user can save components into."""
        return [lib for lib in self._libraries if lib.writable and lib.exists and lib.enabled]

    def get_all_roots(self) -> list[Path]:
        """Return paths of enabled libraries -- used for image path resolution."""
        return [lib.path for lib in self._libraries if lib.exists and lib.enabled]

    # ------------------------------------------------------------------
    # Mutation helpers (update QSettings *and* refresh in one step)
    # ------------------------------------------------------------------

    def add_path(self, path: Path) -> None:
        """Add *path* to the persisted ``library_paths`` list and refresh."""
        paths = self._read_settings_paths()
        resolved = str(path.resolve())
        if resolved not in paths:
            paths.append(resolved)
            self._write_settings_paths(paths)
        self.refresh()

    def remove_path(self, path: Path) -> None:
        """Remove *path* from the persisted ``library_paths`` list and refresh."""
        resolved = str(path.resolve())
        paths = [p for p in self._read_settings_paths() if str(Path(p).resolve()) != resolved]
        self._write_settings_paths(paths)
        self.refresh()

    def set_enabled(self, path: Path, enabled: bool) -> None:
        """Enable or disable a library and refresh."""
        resolved = str(path.resolve())
        disabled = self._read_disabled_paths()
        if enabled:
            disabled.discard(resolved)
        else:
            disabled.add(resolved)
        self._write_disabled_paths(disabled)
        self.refresh()

    def create_library(self, directory: Path) -> LibraryInfo | None:
        """Create *directory* on disk (if needed), add it to settings, and refresh.

        Returns the ``LibraryInfo`` for the new library, or ``None`` on failure.
        """
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _logger.error("Cannot create library directory %s: %s", directory, exc)
            return None
        self.add_path(directory)
        # Find and return the newly added entry
        for lib in self._libraries:
            if lib.path.resolve() == directory.resolve():
                return lib
        return None

    # ------------------------------------------------------------------
    # Refresh / discovery
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the library list from all sources and emit *libraries_changed*."""
        self._libraries = self._discover()
        self.libraries_changed.emit()

    def _discover(self) -> list[LibraryInfo]:
        libs: list[LibraryInfo] = []
        seen: set[str] = set()
        disabled = self._read_disabled_paths()

        def _add(path: Path, source_type: str, writable: bool) -> None:
            key = str(path.resolve())
            if key in seen:
                return
            seen.add(key)
            exists = path.exists() and path.is_dir()
            enabled = key not in disabled
            libs.append(
                LibraryInfo(
                    path=path,
                    name=path.name,
                    source_type=source_type,
                    writable=writable and exists,
                    component_count=self._count_components(path) if exists else 0,
                    exists=exists,
                    enabled=enabled,
                )
            )

        # 1. Built-in library (read-only, shipped with the package)
        _add(get_builtin_library_root(), "builtin", writable=False)

        # 2. Default user library (always writable)
        _add(get_user_library_root(), "user_default", writable=True)

        # 3. Auto-scanned siblings under ComponentLibraries/
        for p in get_all_custom_library_roots():
            _add(p, "scanned", writable=True)

        # 4. Explicitly configured paths from Preferences
        for path_str in self._read_settings_paths():
            if path_str:
                _add(Path(path_str), "settings", writable=True)

        return libs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_components(library_path: Path) -> int:
        try:
            return sum(
                1
                for item in library_path.iterdir()
                if item.is_dir() and (item / "component.json").exists()
            )
        except OSError:
            return 0

    def _read_settings_paths(self) -> list[str]:
        paths = self._settings.get_value("library_paths", [], list)
        return paths if isinstance(paths, list) else []

    def _write_settings_paths(self, paths: list[str]) -> None:
        self._settings.set_value("library_paths", paths)

    def _read_disabled_paths(self) -> set[str]:
        raw = self._settings.get_value("disabled_libraries", [], list)
        return set(raw) if isinstance(raw, list) else set()

    def _write_disabled_paths(self, paths: set[str]) -> None:
        self._settings.set_value("disabled_libraries", sorted(paths))
