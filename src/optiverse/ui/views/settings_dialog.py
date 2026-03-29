"""
Settings dialog for application-wide preferences.

Provides a general-purpose settings interface organized by categories,
allowing easy addition of new settings in the future.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from ...platform.paths import get_user_library_root
from ...services.settings_service import SettingsService


class SettingsDialog(QtWidgets.QDialog):
    """
    General-purpose settings dialog with category-based organization.

    Architecture:
    - Left panel: Category list (Library, Appearance, Performance, etc.)
    - Right panel: Stacked widget with settings pages
    - Easy to extend with new categories and settings

    Signals:
        settings_changed: Emitted when settings are applied
    """

    settings_changed = QtCore.pyqtSignal()

    def __init__(
        self,
        settings_service: SettingsService,
        parent: QtWidgets.QWidget | None = None,
        library_service=None,
    ):
        super().__init__(parent)
        self.settings_service = settings_service
        self._library_service = library_service

        self.setWindowTitle("Preferences")
        self.resize(800, 500)

        # Main layout: horizontal split
        main_layout = QtWidgets.QHBoxLayout(self)

        # Left panel: Category list
        self.category_list = QtWidgets.QListWidget()
        self.category_list.setMaximumWidth(180)
        self.category_list.setIconSize(QtCore.QSize(24, 24))
        self.category_list.currentRowChanged.connect(self._on_category_changed)
        main_layout.addWidget(self.category_list)

        # Right panel: Settings pages
        right_layout = QtWidgets.QVBoxLayout()

        # Title label
        self.page_title = QtWidgets.QLabel()
        self.page_title.setStyleSheet("font-size: 16pt; font-weight: bold; padding: 10px;")
        right_layout.addWidget(self.page_title)

        # Stacked widget for different settings pages
        self.pages_stack = QtWidgets.QStackedWidget()
        right_layout.addWidget(self.pages_stack)

        # Button box
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
            | QtWidgets.QDialogButtonBox.StandardButton.Apply
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        apply_button = button_box.button(QtWidgets.QDialogButtonBox.StandardButton.Apply)
        if apply_button is not None:
            apply_button.clicked.connect(self._apply_settings)
        right_layout.addWidget(button_box)

        main_layout.addLayout(right_layout, 1)

        # Build settings pages
        self._build_pages()

        # Load current settings
        self._load_settings()

        # Select first category
        if self.category_list.count() > 0:
            self.category_list.setCurrentRow(0)

    def _build_pages(self):
        """Build all settings pages and add to category list."""
        # Library Settings
        self._build_library_page()
        self._add_category(
            "Library", "Component library locations and organization", self.library_page
        )

        # Future categories can be added here:
        # self._build_appearance_page()
        # self._add_category("Appearance", "Theme, colors, and UI preferences",
        #                   self.appearance_page)

        # self._build_performance_page()
        # self._add_category("Performance", "Raytracing and rendering options",
        #                   self.performance_page)

    def _add_category(self, name: str, description: str, page: QtWidgets.QWidget):
        """Add a category to the list."""
        item = QtWidgets.QListWidgetItem(name)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, description)
        self.category_list.addItem(item)
        self.pages_stack.addWidget(page)

    def _on_category_changed(self, index: int):
        """Handle category selection change."""
        if index >= 0:
            self.pages_stack.setCurrentIndex(index)
            item = self.category_list.item(index)
            if item is not None:
                item.data(QtCore.Qt.ItemDataRole.UserRole)
                self.page_title.setText(f"{item.text()}")

    def _build_library_page(self):
        """Build the Library settings page with a QTableWidget."""
        self.library_page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.library_page)
        layout.setContentsMargins(10, 10, 10, 10)

        desc = QtWidgets.QLabel(
            "Configure component library locations. Optiverse searches all configured "
            "directories for components. Image paths are stored relative to library "
            "roots, keeping assemblies portable across machines."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: palette(dark); padding: 5px;")
        layout.addWidget(desc)

        # Table widget  ─  Enabled | Name | Path | Components | Status
        self.library_table = QtWidgets.QTableWidget(0, 5)
        self.library_table.setHorizontalHeaderLabels(
            ["", "Name", "Path", "Components", "Status"]
        )
        self.library_table.horizontalHeader().setStretchLastSection(True)
        self.library_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.library_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Interactive
        )
        self.library_table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.library_table.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.library_table.horizontalHeader().setSectionResizeMode(
            4, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.library_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.library_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.library_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.library_table.verticalHeader().setVisible(False)
        self.library_table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.library_table)

        # Buttons row
        btn_layout = QtWidgets.QHBoxLayout()

        self.add_library_btn = QtWidgets.QPushButton("Add Existing...")
        self.add_library_btn.setToolTip("Add an existing folder as a component library")
        self.add_library_btn.clicked.connect(self._add_library_path)
        btn_layout.addWidget(self.add_library_btn)

        self.create_library_btn = QtWidgets.QPushButton("Create New...")
        self.create_library_btn.setToolTip("Create a new empty library folder and register it")
        self.create_library_btn.clicked.connect(self._create_library)
        btn_layout.addWidget(self.create_library_btn)

        self.remove_library_btn = QtWidgets.QPushButton("Remove")
        self.remove_library_btn.setToolTip("Remove selected library from the list (files are kept)")
        self.remove_library_btn.clicked.connect(self._remove_library_path)
        btn_layout.addWidget(self.remove_library_btn)

        btn_layout.addStretch()

        self.open_library_btn = QtWidgets.QPushButton("Open in Finder")
        self.open_library_btn.clicked.connect(self._open_selected_library)
        btn_layout.addWidget(self.open_library_btn)

        layout.addLayout(btn_layout)

        info = QtWidgets.QLabel(
            "Tip: The default user library and auto-scanned libraries are always included. "
            "Add external directories (e.g. git repos) to share components across projects."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: palette(dark); padding: 5px; margin-top: 5px;")
        layout.addWidget(info)

        layout.addStretch()

    def _load_settings(self):
        """Load current settings and populate the library table."""
        self._populate_library_table()

    def _populate_library_table(self):
        """Rebuild the library table from LibraryService (or fallback)."""
        self.library_table.blockSignals(True)
        self.library_table.setRowCount(0)

        if self._library_service is not None:
            for lib in self._library_service.get_all():
                self._add_table_row(
                    name=lib.name,
                    path=str(lib.path),
                    count=lib.component_count,
                    source=lib.source_type,
                    exists=lib.exists,
                    enabled=lib.enabled,
                )
        else:
            default_path = str(get_user_library_root())
            self._add_table_row(
                name=Path(default_path).name,
                path=default_path,
                count=self._count_components(Path(default_path)),
                source="user_default",
                exists=True,
            )
            for p in self.settings_service.get_value("library_paths", [], list):
                if p:
                    pp = Path(p)
                    self._add_table_row(
                        name=pp.name,
                        path=p,
                        count=self._count_components(pp),
                        source="settings",
                        exists=pp.is_dir(),
                    )

        self.library_table.blockSignals(False)

    def _add_table_row(
        self,
        name: str,
        path: str,
        count: int,
        source: str,
        exists: bool,
        enabled: bool = True,
    ):
        row = self.library_table.rowCount()
        self.library_table.insertRow(row)

        # Col 0 — Enabled checkbox
        chk_item = QtWidgets.QTableWidgetItem()
        chk_item.setData(QtCore.Qt.ItemDataRole.UserRole, path)
        chk_item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, source)
        always_on = source == "builtin"
        if always_on:
            chk_item.setFlags(
                QtCore.Qt.ItemFlag.ItemIsSelectable
            )
            chk_item.setCheckState(QtCore.Qt.CheckState.Checked)
        else:
            chk_item.setFlags(
                QtCore.Qt.ItemFlag.ItemIsSelectable
                | QtCore.Qt.ItemFlag.ItemIsEnabled
                | QtCore.Qt.ItemFlag.ItemIsUserCheckable
            )
            chk_item.setCheckState(
                QtCore.Qt.CheckState.Checked if enabled else QtCore.Qt.CheckState.Unchecked
            )
        self.library_table.setItem(row, 0, chk_item)

        # Col 1 — Name
        name_item = QtWidgets.QTableWidgetItem(name)
        if always_on:
            name_item.setForeground(QtGui.QBrush(QtGui.QColor(120, 120, 120)))
        self.library_table.setItem(row, 1, name_item)

        # Col 2 — Path
        path_item = QtWidgets.QTableWidgetItem(path)
        path_item.setToolTip(path)
        self.library_table.setItem(row, 2, path_item)

        # Col 3 — Component count
        count_item = QtWidgets.QTableWidgetItem(str(count))
        count_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.library_table.setItem(row, 3, count_item)

        # Col 4 — Status
        if not exists:
            status = "Missing"
        elif source == "builtin":
            status = "Built-in"
        elif source == "user_default":
            status = "Default"
        elif source == "scanned":
            status = "Auto"
        else:
            status = "OK"
        status_item = QtWidgets.QTableWidgetItem(status)
        status_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        if not exists:
            status_item.setForeground(QtGui.QBrush(QtGui.QColor(200, 60, 60)))
        self.library_table.setItem(row, 4, status_item)

    @staticmethod
    def _count_components(library_path: Path) -> int:
        if not library_path.exists() or not library_path.is_dir():
            return 0
        try:
            return sum(
                1 for item in library_path.iterdir()
                if item.is_dir() and (item / "component.json").exists()
            )
        except OSError:
            return 0

    def _on_cell_changed(self, row: int, col: int):
        """Handle checkbox toggle in the Enabled column."""
        if col != 0 or self._library_service is None:
            return
        chk_item = self.library_table.item(row, 0)
        if not chk_item:
            return
        source = chk_item.data(QtCore.Qt.ItemDataRole.UserRole + 1)
        if source == "builtin":
            return
        path = chk_item.data(QtCore.Qt.ItemDataRole.UserRole)
        enabled = chk_item.checkState() == QtCore.Qt.CheckState.Checked
        self._library_service.set_enabled(Path(path), enabled)

    def _add_library_path(self):
        """Add an existing directory as a library."""
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select Component Library Directory",
            "",
            QtWidgets.QFileDialog.Option.ShowDirsOnly,
        )
        if not path:
            return

        # Duplicate check
        for row in range(self.library_table.rowCount()):
            item = self.library_table.item(row, 0)
            if item and item.data(QtCore.Qt.ItemDataRole.UserRole) == path:
                QtWidgets.QMessageBox.information(
                    self, "Already Added", f"This library path is already in the list:\n{path}"
                )
                return

        if self._library_service is not None:
            self._library_service.add_path(Path(path))
            self._populate_library_table()
        else:
            pp = Path(path)
            self._add_table_row(
                name=pp.name,
                path=path,
                count=self._count_components(pp),
                source="settings",
                exists=pp.is_dir(),
            )

    def _create_library(self):
        """Create a brand-new library directory and add it."""
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select or Create Library Directory",
            "",
            QtWidgets.QFileDialog.Option.ShowDirsOnly,
        )
        if not path:
            return

        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)

        if self._library_service is not None:
            self._library_service.create_library(target)
            self._populate_library_table()
        else:
            self._add_table_row(
                name=target.name,
                path=str(target),
                count=0,
                source="settings",
                exists=True,
            )

    def _remove_library_path(self):
        """Remove selected library path (only settings-added paths)."""
        row = self.library_table.currentRow()
        if row < 0:
            return

        name_item = self.library_table.item(row, 0)
        if not name_item:
            return

        source = name_item.data(QtCore.Qt.ItemDataRole.UserRole + 1)
        if source in ("builtin", "user_default", "scanned"):
            QtWidgets.QMessageBox.information(
                self,
                "Cannot Remove",
                "This library is auto-discovered and cannot be removed from preferences.\n"
                "To stop it from appearing, move or rename the folder on disk.",
            )
            return

        path = name_item.data(QtCore.Qt.ItemDataRole.UserRole)
        reply = QtWidgets.QMessageBox.question(
            self,
            "Remove Library Path",
            f"Remove this library path from the list?\n\n{path}\n\n"
            "The folder and its files will not be deleted.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )

        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            if self._library_service is not None:
                self._library_service.remove_path(Path(path))
                self._populate_library_table()
            else:
                self.library_table.removeRow(row)

    def _open_selected_library(self):
        """Open selected library in the system file manager."""
        row = self.library_table.currentRow()
        if row < 0:
            return
        name_item = self.library_table.item(row, 0)
        if name_item:
            path = name_item.data(QtCore.Qt.ItemDataRole.UserRole)
            if path:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def _apply_settings(self):
        """Apply settings without closing dialog."""
        self._save_settings()
        self.settings_changed.emit()

    def _save_settings(self):
        """Save settings to SettingsService."""
        # When using LibraryService, mutations are already persisted live.
        if self._library_service is not None:
            return

        # Fallback: collect paths from table (skip builtin/user_default/scanned)
        library_paths = []
        for i in range(self.library_table.rowCount()):
            name_item = self.library_table.item(i, 0)
            if not name_item:
                continue
            source = name_item.data(QtCore.Qt.ItemDataRole.UserRole + 1)
            if source == "settings":
                path = name_item.data(QtCore.Qt.ItemDataRole.UserRole)
                if path:
                    library_paths.append(path)
        self.settings_service.set_value("library_paths", library_paths)

    def accept(self):
        """Override accept to save settings."""
        self._save_settings()
        self.settings_changed.emit()
        super().accept()
