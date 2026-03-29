from __future__ import annotations

from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from ...core.color_utils import (
    LASER_WAVELENGTHS,
    hex_from_qcolor,
    qcolor_from_hex,
    wavelength_to_hex,
)
from ...core.models import SourceParams
from ...core.raytracing_math import qt_angle_to_user, user_angle_to_qt
from ...ui.widgets.smart_spinbox import SmartDoubleSpinBox, SmartSpinBox
from ..base_obj import BaseObj
from ..type_registry import deserialize_item, register_type, serialize_item


@register_type("source", SourceParams)
class SourceItem(BaseObj):
    """
    Optical source element with configurable parameters.

    - Aperture size, number of rays, angular spread
    - Custom color via hex picker
    - Full editor dialog
    - Serialization support
    """

    type_name: str = "source"

    def __init__(self, params: SourceParams, item_uuid: str | None = None):
        super().__init__(item_uuid)
        self.params = params
        # Note: z-value is set by layer panel based on tree position
        self._color = qcolor_from_hex(self.params.color_hex)
        self._update_shape()
        self.setPos(self.params.x_mm, self.params.y_mm)
        self.setRotation(user_angle_to_qt(self.params.angle_deg))
        self._ready = True  # Enable position sync

    def _sync_params_from_item(self):
        """Sync params from item position/rotation."""
        self.params.x_mm = float(self.pos().x())
        self.params.y_mm = float(self.pos().y())
        self.params.angle_deg = qt_angle_to_user(self.rotation())

    def _update_shape(self):
        """Update geometry based on aperture size."""
        self.prepareGeometryChange()
        self._half = max(1.0, self.params.size_mm / 2.0)

        # Vertical bar representing aperture
        self._bar = QtGui.QPainterPath()
        self._bar.moveTo(0, -self._half)
        self._bar.lineTo(0, self._half)

        # Horizontal arrow showing direction
        self._arrow = QtGui.QPainterPath()
        self._arrow.moveTo(0, 0)
        self._arrow.lineTo(18.0, 0.0)

    def _hitbox_rect(self) -> QtCore.QRectF:
        """Padded rectangular hitbox around the visual elements (bar + arrow)."""
        pad = 8.0
        return QtCore.QRectF(-pad, -self._half - pad, 18.0 + 2 * pad, self._half * 2 + 2 * pad)

    def boundingRect(self) -> QtCore.QRectF:
        return self._hitbox_rect().adjusted(-2, -2, 2, 2)

    def shape(self) -> QtGui.QPainterPath:
        path = QtGui.QPainterPath()
        path.addRect(self._hitbox_rect())
        return path

    def paint(self, p: QtGui.QPainter | None, opt, widget=None):
        if p is None:
            return
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pen1 = QtGui.QPen(self._color, 7)
        pen1.setCosmetic(True)
        pen2 = QtGui.QPen(self._color, 3)
        pen2.setCosmetic(True)
        p.setPen(pen1)
        p.drawPath(self._bar)
        p.setPen(pen2)
        p.drawPath(self._arrow)

        hit = self._hitbox_rect()
        if self.isSelected():
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(30, 144, 255, 70))
            p.drawRect(hit)
        elif getattr(self, "_hovered", False):
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(30, 144, 255, 35))
            p.drawRect(hit)

    def open_editor(self):
        """Open editor dialog for source parameters."""
        # Capture initial state for undo
        initial_state = self.capture_state()

        parent = self._parent_window()
        d = QtWidgets.QDialog(parent)
        d.setWindowTitle("Edit Source")
        f = QtWidgets.QFormLayout(d)

        # Save initial state for rollback on cancel (x, y, angle)
        initial_x = self.pos().x()
        initial_y = self.pos().y()
        # Convert Qt angle to user angle (CW from up)
        initial_ang = qt_angle_to_user(self.rotation())

        # Position and orientation
        x = SmartDoubleSpinBox()
        x.setRange(-1e6, 1e6)
        x.setDecimals(3)
        x.setSuffix(" mm")
        x.setValue(initial_x)

        y = SmartDoubleSpinBox()
        y.setRange(-1e6, 1e6)
        y.setDecimals(3)
        y.setSuffix(" mm")
        y.setValue(initial_y)

        ang = SmartDoubleSpinBox()
        ang.setRange(-1e6, 1e6)
        ang.setDecimals(2)
        ang.setSuffix(" °")
        ang.setValue(initial_ang)
        ang.setToolTip(
            "Optical axis angle - direction rays emit (0° = right →, 90° = down ↓, 180° = left ←)"
        )

        # Live update connections
        def update_position():
            self.setPos(x.value(), y.value())
            self.params.x_mm = x.value()
            self.params.y_mm = y.value()
            self.edited.emit()

        def update_angle():
            user_angle = ang.value()
            self.setRotation(user_angle_to_qt(user_angle))
            self.params.angle_deg = user_angle
            self.edited.emit()

        # Update spinboxes when item is modified externally (e.g., Ctrl+drag rotation)
        def sync_from_item():
            # Block signals to prevent recursive updates
            x.blockSignals(True)
            y.blockSignals(True)
            ang.blockSignals(True)

            # Convert Qt angle to user angle
            user_angle = qt_angle_to_user(self.rotation())

            x.setValue(self.pos().x())
            y.setValue(self.pos().y())
            ang.setValue(user_angle)

            x.blockSignals(False)
            y.blockSignals(False)
            ang.blockSignals(False)

        x.valueChanged.connect(update_position)
        y.valueChanged.connect(update_position)
        ang.valueChanged.connect(update_angle)

        # Connect to item's edited signal to sync spinboxes
        self.edited.connect(sync_from_item)

        # Source type selector
        source_type_combo = QtWidgets.QComboBox()
        source_type_combo.addItems(["Geometric Rays", "Gaussian Beam"])
        is_gaussian = self.params.source_type == "gaussian"
        source_type_combo.setCurrentIndex(1 if is_gaussian else 0)

        # Beam waist (only for Gaussian mode)
        beam_waist = SmartDoubleSpinBox()
        beam_waist.setRange(0.001, 1e4)
        beam_waist.setDecimals(4)
        beam_waist.setSuffix(" mm")
        beam_waist.setValue(self.params.beam_waist_mm)
        beam_waist.setToolTip("1/e² beam waist radius w₀ at the source position")

        # Label for beam waist (so we can show/hide it)
        beam_waist_label = QtWidgets.QLabel("Beam waist (w₀)")

        # Labels for ray-specific fields (so we can show/hide per mode)
        size_label = QtWidgets.QLabel("Aperture size")
        nr_label = QtWidgets.QLabel("# Rays")
        spr_label = QtWidgets.QLabel("Angular spread (±)")

        def _set_mode_visibility(is_gauss: bool):
            """Toggle field visibility based on source type."""
            beam_waist.setVisible(is_gauss)
            beam_waist_label.setVisible(is_gauss)
            size.setVisible(not is_gauss)
            size_label.setVisible(not is_gauss)
            nr.setVisible(not is_gauss)
            nr_label.setVisible(not is_gauss)
            spr.setVisible(not is_gauss)
            spr_label.setVisible(not is_gauss)

        def update_source_type():
            is_gauss = source_type_combo.currentIndex() == 1
            self.params.source_type = "gaussian" if is_gauss else "ray"
            _set_mode_visibility(is_gauss)
            self.edited.emit()

        def update_beam_waist():
            self.params.beam_waist_mm = beam_waist.value()
            self.edited.emit()

        source_type_combo.currentIndexChanged.connect(lambda: update_source_type())
        beam_waist.valueChanged.connect(update_beam_waist)

        # Source parameters
        size = SmartDoubleSpinBox()
        size.setRange(0, 1e6)
        size.setDecimals(3)
        size.setSuffix(" mm")
        size.setValue(self.params.size_mm)

        nr = SmartSpinBox()
        nr.setRange(1, 2001)
        nr.setValue(self.params.n_rays)

        rlen = SmartDoubleSpinBox()
        rlen.setRange(1, 1e7)
        rlen.setDecimals(1)
        rlen.setSuffix(" mm")
        rlen.setValue(self.params.ray_length_mm)

        spr = SmartDoubleSpinBox()
        spr.setRange(0, 89.9)
        spr.setDecimals(2)
        spr.setSuffix(" °")
        spr.setValue(self.params.spread_deg)

        # Live update connections for source parameters
        def update_size():
            self.params.size_mm = size.value()
            self._update_shape()
            self.edited.emit()

        def update_n_rays():
            self.params.n_rays = nr.value()
            self.edited.emit()

        def update_ray_length():
            self.params.ray_length_mm = rlen.value()
            self.edited.emit()

        def update_spread():
            self.params.spread_deg = spr.value()
            self.edited.emit()

        size.valueChanged.connect(update_size)
        nr.valueChanged.connect(update_n_rays)
        rlen.valueChanged.connect(update_ray_length)
        spr.valueChanged.connect(update_spread)

        # Wavelength controls
        wl_mode = QtWidgets.QComboBox()
        wl_mode.addItems(["Custom Color", "Wavelength"])
        # Detect mode: if color matches wavelength-derived color, we're in wavelength mode
        is_wl_mode = self.params.wavelength_nm > 0 and self.params.color_hex == wavelength_to_hex(
            self.params.wavelength_nm
        )
        wl_mode.setCurrentIndex(1 if is_wl_mode else 0)

        # Wavelength preset dropdown
        wl_preset = QtWidgets.QComboBox()
        wl_preset.addItem("Custom...", 0.0)
        for name, wl in LASER_WAVELENGTHS.items():
            wl_preset.addItem(name, wl)

        # Find current wavelength in presets
        if self.params.wavelength_nm > 0:
            for i in range(wl_preset.count()):
                if abs(wl_preset.itemData(i) - self.params.wavelength_nm) < 0.1:
                    wl_preset.setCurrentIndex(i)
                    break

        # Wavelength spinbox (always enabled)
        wl_spin = SmartDoubleSpinBox()
        wl_spin.setRange(200, 2000)
        wl_spin.setDecimals(1)
        wl_spin.setSuffix(" nm")
        wl_spin.setValue(self.params.wavelength_nm if self.params.wavelength_nm > 0 else 633.0)

        # Color picker
        color_btn = QtWidgets.QToolButton()
        color_btn.setText("Pick…")
        color_disp = QtWidgets.QLabel(self.params.color_hex)
        color_btn.setEnabled(not is_wl_mode)
        color_disp.setEnabled(not is_wl_mode)

        def paint_chip(lbl: QtWidgets.QLabel, hexstr: str):
            pm = QtGui.QPixmap(40, 16)
            pm.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(pm)
            painter.fillRect(0, 0, 40, 16, qcolor_from_hex(hexstr))
            painter.end()
            lbl.setPixmap(pm)

        chip = QtWidgets.QLabel()
        if is_wl_mode:
            paint_chip(chip, wavelength_to_hex(self.params.wavelength_nm))
        else:
            paint_chip(chip, self.params.color_hex)

        def pick_color():
            c = QtWidgets.QColorDialog.getColor(
                self._color,
                d,
                "Choose Ray Color",
                QtWidgets.QColorDialog.ColorDialogOption.DontUseNativeDialog,
            )
            if c.isValid():
                self._color = c
                color_disp.setText(c.name())
                paint_chip(chip, c.name())
                _apply_color_to_source()

        def _apply_color_to_source():
            """Apply current color/wavelength settings to the source live."""
            self.params.wavelength_nm = wl_spin.value()
            if wl_mode.currentText() == "Wavelength":
                self.params.color_hex = wavelength_to_hex(self.params.wavelength_nm)
                self._color = qcolor_from_hex(self.params.color_hex)
            else:
                self.params.color_hex = hex_from_qcolor(self._color)
            self.update()
            self.edited.emit()

        def update_from_wavelength():
            """Update wavelength param and, if in Wavelength mode, update color."""
            if wl_mode.currentText() == "Wavelength":
                wl = wl_spin.value()
                paint_chip(chip, wavelength_to_hex(wl))
            _apply_color_to_source()

        def on_mode_changed(mode: str):
            """Handle wavelength mode change."""
            use_wl = mode == "Wavelength"
            # Wavelength controls are always enabled
            color_btn.setEnabled(not use_wl)
            color_disp.setEnabled(not use_wl)
            if use_wl:
                update_from_wavelength()
            else:
                paint_chip(chip, color_disp.text())
                _apply_color_to_source()

        def on_preset_changed(idx: int):
            """Handle wavelength preset selection."""
            wl = wl_preset.itemData(idx)
            if wl > 0:
                wl_spin.setValue(wl)
                # Only update chip if in Wavelength mode
                if wl_mode.currentText() == "Wavelength":
                    update_from_wavelength()

        wl_mode.currentTextChanged.connect(on_mode_changed)
        wl_preset.currentIndexChanged.connect(on_preset_changed)
        wl_spin.valueChanged.connect(lambda: update_from_wavelength())

        row_color = QtWidgets.QHBoxLayout()
        row_color.addWidget(color_btn)
        row_color.addWidget(color_disp)
        row_color.addWidget(chip)
        row_color.addStretch(1)
        color_btn.clicked.connect(pick_color)

        # Polarization controls
        pol_type = QtWidgets.QComboBox()
        pol_type.addItems(
            [
                "horizontal",
                "vertical",
                "+45",
                "-45",
                "circular_right",
                "circular_left",
                "linear",
            ]
        )
        # Set current value
        try:
            idx = pol_type.findText(self.params.polarization_type)
            if idx >= 0:
                pol_type.setCurrentIndex(idx)
        except AttributeError:
            pass  # params may not have polarization_type yet

        pol_angle = SmartDoubleSpinBox()
        pol_angle.setRange(-180, 180)
        pol_angle.setDecimals(1)
        pol_angle.setSuffix(" °")
        pol_angle.setValue(self.params.polarization_angle_deg)
        pol_angle.setEnabled(self.params.polarization_type == "linear")

        # Live update connections for polarization
        def update_polarization():
            self.params.polarization_type = pol_type.currentText()
            self.params.polarization_angle_deg = pol_angle.value()
            pol_angle.setEnabled(pol_type.currentText() == "linear")
            self.edited.emit()

        pol_type.currentTextChanged.connect(update_polarization)
        pol_angle.valueChanged.connect(update_polarization)

        # Set initial field visibility based on source type
        _set_mode_visibility(is_gaussian)

        # Add all fields to form
        f.addRow("X Position", x)
        f.addRow("Y Position", y)
        f.addRow("Optical Axis Angle", ang)
        f.addRow("Source Type", source_type_combo)
        f.addRow(beam_waist_label, beam_waist)
        f.addRow(size_label, size)
        f.addRow(nr_label, nr)
        f.addRow("Ray length", rlen)
        f.addRow(spr_label, spr)
        f.addRow("Color Mode", wl_mode)
        f.addRow("Wavelength Preset", wl_preset)
        f.addRow("Wavelength", wl_spin)
        f.addRow("Custom Color", row_color)
        f.addRow("Polarization", pol_type)
        f.addRow("Polarization angle", pol_angle)

        # Buttons
        btn = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        f.addRow(btn)
        btn.accepted.connect(d.accept)
        btn.rejected.connect(d.reject)

        # Apply other changes if accepted, rollback x/y/angle if cancelled
        result = d.exec()

        # Disconnect the sync signal to prevent memory leaks
        self.edited.disconnect(sync_from_item)

        if result:
            # All params already applied live — just create undo command
            final_state = self.capture_state()
            if initial_state != final_state:
                from ...core.undo_commands import PropertyChangeCommand

                cmd = PropertyChangeCommand(self, initial_state, final_state)
                self.commandCreated.emit(cmd)
        else:
            # User clicked Cancel - restore initial state
            self.apply_state(initial_state)

    def apply_state(self, state: dict[str, Any]) -> None:
        """Override to sync _color from params after base apply."""
        super().apply_state(state)
        self._color = qcolor_from_hex(self.params.color_hex)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        d = serialize_item(self)
        # Force live color (SourceItem-specific)
        d["color_hex"] = hex_from_qcolor(self._color)
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> SourceItem:
        """Static factory method: deserialize from dictionary and return new SourceItem."""
        item = deserialize_item(d)
        if not isinstance(item, SourceItem):
            raise TypeError(f"Expected SourceItem, got {type(item)}")
        return item
