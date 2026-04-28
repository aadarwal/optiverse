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
        self.resize(850, 550)

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
        self._build_general_page()
        self._add_category("General", "Application behavior", self.general_page)

        self._build_appearance_page()
        self._add_category("Appearance", "Theme and display options", self.appearance_page)

        self._build_canvas_page()
        self._add_category(
            "Canvas & Editing", "Snap, grid, and editing defaults", self.canvas_page
        )

        self._build_export_page()
        self._add_category("Export Defaults", "Default export settings", self.export_page)

        self._build_library_page()
        self._add_category(
            "Library", "Component library locations and organization", self.library_page
        )

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

    # ── Helper ──────────────────────────────────────────────────────────

    @staticmethod
    def _make_description(text: str) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: palette(dark); padding: 5px;")
        return lbl

    # ── General page ─────────────────────────────────────────────────────

    def _build_general_page(self):
        self.general_page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.general_page)
        layout.setContentsMargins(10, 10, 10, 10)

        layout.addWidget(
            self._make_description(
                "Configure autosave behavior and recent file tracking."
            )
        )

        # Autosave group
        grp_autosave = QtWidgets.QGroupBox("Autosave")
        form_as = QtWidgets.QFormLayout(grp_autosave)

        self._chk_autosave = QtWidgets.QCheckBox("Enable autosave")
        form_as.addRow("", self._chk_autosave)

        self._spin_autosave_interval = QtWidgets.QDoubleSpinBox()
        self._spin_autosave_interval.setRange(0.5, 60.0)
        self._spin_autosave_interval.setSingleStep(0.5)
        self._spin_autosave_interval.setDecimals(1)
        self._spin_autosave_interval.setSuffix(" s")
        form_as.addRow("Interval:", self._spin_autosave_interval)

        layout.addWidget(grp_autosave)

        # Recent files group
        grp_recent = QtWidgets.QGroupBox("Recent Files")
        form_rf = QtWidgets.QFormLayout(grp_recent)

        self._spin_max_recent = QtWidgets.QSpinBox()
        self._spin_max_recent.setRange(1, 50)
        form_rf.addRow("Maximum entries:", self._spin_max_recent)

        layout.addWidget(grp_recent)
        layout.addStretch()

    # ── Appearance page ──────────────────────────────────────────────────

    def _build_appearance_page(self):
        self.appearance_page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.appearance_page)
        layout.setContentsMargins(10, 10, 10, 10)

        layout.addWidget(
            self._make_description("Configure visual theme and display options.")
        )

        grp_theme = QtWidgets.QGroupBox("Theme")
        form_th = QtWidgets.QFormLayout(grp_theme)
        self._chk_dark_mode = QtWidgets.QCheckBox("Dark mode")
        form_th.addRow("", self._chk_dark_mode)
        layout.addWidget(grp_theme)

        grp_display = QtWidgets.QGroupBox("Display")
        form_dp = QtWidgets.QFormLayout(grp_display)
        self._chk_scale_bar = QtWidgets.QCheckBox("Show scale bar")
        form_dp.addRow("", self._chk_scale_bar)
        layout.addWidget(grp_display)

        layout.addStretch()

    # ── Canvas & Editing page ────────────────────────────────────────────

    def _build_canvas_page(self):
        self.canvas_page = QtWidgets.QWidget()

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)

        inner = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(inner)
        layout.setContentsMargins(10, 10, 10, 10)

        layout.addWidget(
            self._make_description(
                "Defaults for snapping, grid, rotation, raytracing, and clipboard behavior. "
                "Toggle settings (snap, autotrace) set the initial state on startup; "
                "use the toolbar to change them during a session."
            )
        )

        # Grid & Snapping
        grp_snap = QtWidgets.QGroupBox("Grid && Snapping")
        form_sn = QtWidgets.QFormLayout(grp_snap)

        self._chk_snap_grid = QtWidgets.QCheckBox("Snap to grid on startup")
        form_sn.addRow("", self._chk_snap_grid)

        self._spin_grid_size = QtWidgets.QDoubleSpinBox()
        self._spin_grid_size.setRange(0.1, 100.0)
        self._spin_grid_size.setSingleStep(0.5)
        self._spin_grid_size.setDecimals(1)
        self._spin_grid_size.setSuffix(" mm")
        form_sn.addRow("Grid size:", self._spin_grid_size)

        self._chk_magnetic = QtWidgets.QCheckBox("Magnetic snap on startup")
        form_sn.addRow("", self._chk_magnetic)

        self._spin_mag_tol = QtWidgets.QDoubleSpinBox()
        self._spin_mag_tol.setRange(1.0, 50.0)
        self._spin_mag_tol.setSingleStep(1.0)
        self._spin_mag_tol.setDecimals(1)
        self._spin_mag_tol.setSuffix(" px")
        form_sn.addRow("Snap tolerance:", self._spin_mag_tol)

        layout.addWidget(grp_snap)

        # Rotation
        grp_rot = QtWidgets.QGroupBox("Rotation")
        form_rt = QtWidgets.QFormLayout(grp_rot)

        self._spin_rot_snap = QtWidgets.QDoubleSpinBox()
        self._spin_rot_snap.setRange(1.0, 90.0)
        self._spin_rot_snap.setSingleStep(5.0)
        self._spin_rot_snap.setDecimals(1)
        self._spin_rot_snap.setSuffix("°")
        form_rt.addRow("Snap angle:", self._spin_rot_snap)

        self._spin_wheel_sens = QtWidgets.QDoubleSpinBox()
        self._spin_wheel_sens.setRange(0.1, 10.0)
        self._spin_wheel_sens.setSingleStep(0.5)
        self._spin_wheel_sens.setDecimals(1)
        self._spin_wheel_sens.setSuffix(" °/step")
        form_rt.addRow("Wheel sensitivity:", self._spin_wheel_sens)

        layout.addWidget(grp_rot)

        # Raytracing
        grp_ray = QtWidgets.QGroupBox("Raytracing")
        form_ry = QtWidgets.QFormLayout(grp_ray)

        self._chk_autotrace = QtWidgets.QCheckBox("Auto-trace on startup")
        form_ry.addRow("", self._chk_autotrace)

        self._spin_ray_width = QtWidgets.QDoubleSpinBox()
        self._spin_ray_width.setRange(0.5, 20.0)
        self._spin_ray_width.setSingleStep(0.5)
        self._spin_ray_width.setDecimals(1)
        self._spin_ray_width.setSuffix(" px")
        form_ry.addRow("Default ray width:", self._spin_ray_width)

        self._spin_max_events = QtWidgets.QSpinBox()
        self._spin_max_events.setRange(10, 500)
        self._spin_max_events.setSingleStep(10)
        form_ry.addRow("Max ray events:", self._spin_max_events)

        layout.addWidget(grp_ray)

        # Clipboard
        grp_clip = QtWidgets.QGroupBox("Clipboard")
        form_cl = QtWidgets.QFormLayout(grp_clip)

        self._spin_clone_x = QtWidgets.QDoubleSpinBox()
        self._spin_clone_x.setRange(1.0, 100.0)
        self._spin_clone_x.setSingleStep(5.0)
        self._spin_clone_x.setDecimals(1)
        self._spin_clone_x.setSuffix(" mm")
        form_cl.addRow("Clone offset X:", self._spin_clone_x)

        self._spin_clone_y = QtWidgets.QDoubleSpinBox()
        self._spin_clone_y.setRange(1.0, 100.0)
        self._spin_clone_y.setSingleStep(5.0)
        self._spin_clone_y.setDecimals(1)
        self._spin_clone_y.setSuffix(" mm")
        form_cl.addRow("Clone offset Y:", self._spin_clone_y)

        layout.addWidget(grp_clip)
        layout.addStretch()

        scroll.setWidget(inner)
        page_layout = QtWidgets.QVBoxLayout(self.canvas_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)

    # ── Export Defaults page ─────────────────────────────────────────────

    def _build_export_page(self):
        self.export_page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.export_page)
        layout.setContentsMargins(10, 10, 10, 10)

        layout.addWidget(
            self._make_description(
                "Default values used in export dialogs. "
                "You can still override these each time you export."
            )
        )

        grp_png = QtWidgets.QGroupBox("PNG Export")
        form_png = QtWidgets.QFormLayout(grp_png)
        self._spin_png_scale = QtWidgets.QDoubleSpinBox()
        self._spin_png_scale.setRange(1.0, 10.0)
        self._spin_png_scale.setSingleStep(0.5)
        self._spin_png_scale.setDecimals(1)
        self._spin_png_scale.setSuffix("x")
        form_png.addRow("Default scale:", self._spin_png_scale)
        layout.addWidget(grp_png)

        grp_pdf = QtWidgets.QGroupBox("PDF Export")
        form_pdf = QtWidgets.QFormLayout(grp_pdf)
        self._spin_pdf_dpi = QtWidgets.QSpinBox()
        self._spin_pdf_dpi.setRange(72, 600)
        self._spin_pdf_dpi.setSingleStep(50)
        self._spin_pdf_dpi.setSuffix(" DPI")
        form_pdf.addRow("Default DPI:", self._spin_pdf_dpi)
        layout.addWidget(grp_pdf)

        grp_margin = QtWidgets.QGroupBox("General")
        form_mg = QtWidgets.QFormLayout(grp_margin)
        self._spin_export_margin = QtWidgets.QSpinBox()
        self._spin_export_margin.setRange(0, 100)
        self._spin_export_margin.setSingleStep(5)
        self._spin_export_margin.setSuffix(" mm")
        form_mg.addRow("Export margin:", self._spin_export_margin)
        layout.addWidget(grp_margin)

        layout.addStretch()

    # ── Library page ─────────────────────────────────────────────────────

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
        """Load current settings into all UI widgets."""
        s = self.settings_service

        # General
        self._chk_autosave.setChecked(s.get_value("general/autosave_enabled", True, bool))
        self._spin_autosave_interval.setValue(
            s.get_value("general/autosave_interval_ms", 1000, int) / 1000.0
        )
        self._spin_max_recent.setValue(s.get_value("general/max_recent_files", 10, int))

        # Appearance
        self._chk_dark_mode.setChecked(s.get_value("dark_mode", False, bool))
        self._chk_scale_bar.setChecked(s.get_value("appearance/show_scale_bar", True, bool))

        # Canvas & Editing
        self._chk_snap_grid.setChecked(s.get_value("canvas/snap_to_grid", False, bool))
        self._spin_grid_size.setValue(s.get_value("canvas/grid_snap_size_mm", 1.0, float))
        self._chk_magnetic.setChecked(s.get_value("magnetic_snap", True, bool))
        self._spin_mag_tol.setValue(
            s.get_value("canvas/magnetic_snap_tolerance_px", 10.0, float)
        )
        self._spin_rot_snap.setValue(
            s.get_value("canvas/rotation_snap_angle_deg", 45.0, float)
        )
        self._spin_wheel_sens.setValue(
            s.get_value("canvas/wheel_rotation_deg_per_step", 2.0, float)
        )
        self._chk_autotrace.setChecked(s.get_value("canvas/autotrace", True, bool))
        self._spin_ray_width.setValue(
            s.get_value("canvas/default_ray_width_px", 2.0, float)
        )
        self._spin_max_events.setValue(
            s.get_value("canvas/max_raytracing_events", 80, int)
        )
        self._spin_clone_x.setValue(
            s.get_value("canvas/clone_offset_x_mm", 20.0, float)
        )
        self._spin_clone_y.setValue(
            s.get_value("canvas/clone_offset_y_mm", 20.0, float)
        )

        # Export
        self._spin_png_scale.setValue(
            s.get_value("export/default_png_scale", 4.0, float)
        )
        self._spin_pdf_dpi.setValue(s.get_value("export/default_pdf_dpi", 300, int))
        self._spin_export_margin.setValue(
            s.get_value("export/export_margin_mm", 20, int)
        )

        # Library
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
        chk_item.setFlags(
            QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsUserCheckable
        )
        chk_item.setCheckState(
            QtCore.Qt.CheckState.Checked
            if enabled
            else QtCore.Qt.CheckState.Unchecked
        )
        self.library_table.setItem(row, 0, chk_item)

        # Col 1 — Name
        name_item = QtWidgets.QTableWidgetItem(name)
        self.library_table.setItem(row, 1, name_item)

        # Col 2 — Path
        path_item = QtWidgets.QTableWidgetItem(path)
        path_item.setToolTip(path)
        self.library_table.setItem(row, 2, path_item)

        # Col 3 — Component count
        count_item = QtWidgets.QTableWidgetItem(str(count))
        count_item.setTextAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
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
        status_item.setTextAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        if not exists:
            status_item.setForeground(QtGui.QBrush(QtGui.QColor(220, 60, 60)))
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
        """Handle checkbox changes in the library table."""
        if col != 0:
            return

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
        """Save settings to SettingsService (called on OK / Apply)."""
        s = self.settings_service

        # General
        s.set_value("general/autosave_enabled", self._chk_autosave.isChecked())
        s.set_value(
            "general/autosave_interval_ms",
            int(self._spin_autosave_interval.value() * 1000),
        )
        s.set_value("general/max_recent_files", self._spin_max_recent.value())

        # Appearance
        s.set_value("dark_mode", self._chk_dark_mode.isChecked())
        s.set_value("appearance/show_scale_bar", self._chk_scale_bar.isChecked())

        # Canvas & Editing
        s.set_value("canvas/snap_to_grid", self._chk_snap_grid.isChecked())
        s.set_value("canvas/grid_snap_size_mm", self._spin_grid_size.value())
        s.set_value("magnetic_snap", self._chk_magnetic.isChecked())
        s.set_value(
            "canvas/magnetic_snap_tolerance_px", self._spin_mag_tol.value()
        )
        s.set_value("canvas/rotation_snap_angle_deg", self._spin_rot_snap.value())
        s.set_value(
            "canvas/wheel_rotation_deg_per_step", self._spin_wheel_sens.value()
        )
        s.set_value("canvas/autotrace", self._chk_autotrace.isChecked())
        s.set_value("canvas/default_ray_width_px", self._spin_ray_width.value())
        s.set_value("canvas/max_raytracing_events", self._spin_max_events.value())
        s.set_value("canvas/clone_offset_x_mm", self._spin_clone_x.value())
        s.set_value("canvas/clone_offset_y_mm", self._spin_clone_y.value())

        # Export
        s.set_value("export/default_png_scale", self._spin_png_scale.value())
        s.set_value("export/default_pdf_dpi", self._spin_pdf_dpi.value())
        s.set_value("export/export_margin_mm", self._spin_export_margin.value())

        # Library
        if self._library_service is not None:
            # Batch-apply enabled/disabled states from checkboxes
            disabled: set[str] = set()
            for i in range(self.library_table.rowCount()):
                chk = self.library_table.item(i, 0)
                if not chk:
                    continue
                path = chk.data(QtCore.Qt.ItemDataRole.UserRole)
                if chk.checkState() != QtCore.Qt.CheckState.Checked:
                    disabled.add(str(Path(path).resolve()))
            self._library_service._write_disabled_paths(disabled)
            self._library_service.refresh()
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
