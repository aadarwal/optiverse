"""Dialog for applying one component's properties to other components on the canvas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6 import QtWidgets

from ...core.interface_types import INTERFACE_TYPES

if TYPE_CHECKING:
    from ...objects.generic.component_item import ComponentItem


class ApplyPropertiesToAllDialog(QtWidgets.QDialog):
    """Confirmation dialog that lets the user choose scope and which properties to propagate."""

    def __init__(
        self,
        source: ComponentItem,
        all_items: list[ComponentItem],
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Apply Properties to Other Components")
        self.setMinimumWidth(420)

        self._source = source
        self._all_items = [item for item in all_items if item is not source]

        self._scope: str = "all"
        self._property_checks: dict[str, QtWidgets.QCheckBox] = {}

        self._build_ui()
        self._update_count()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # --- Scope selector ---
        scope_group = QtWidgets.QGroupBox("Apply to")
        scope_layout = QtWidgets.QVBoxLayout(scope_group)

        self._rb_all = QtWidgets.QRadioButton("All components on canvas")
        self._rb_category = QtWidgets.QRadioButton("Same category only")
        self._rb_selected = QtWidgets.QRadioButton("Selected components only")
        self._rb_all.setChecked(True)

        for rb in (self._rb_all, self._rb_category, self._rb_selected):
            rb.toggled.connect(self._update_count)
            scope_layout.addWidget(rb)

        self._count_label = QtWidgets.QLabel()
        scope_layout.addWidget(self._count_label)
        layout.addWidget(scope_group)

        # --- Property checkboxes ---
        props_group = QtWidgets.QGroupBox("Properties to apply")
        props_layout = QtWidgets.QVBoxLayout(props_group)

        cb_height = QtWidgets.QCheckBox("Object height")
        cb_height.setChecked(True)
        self._property_checks["object_height_mm"] = cb_height
        props_layout.addWidget(cb_height)

        if self._source.params.interfaces:
            props_layout.addWidget(self._separator())

            seen_types: set[str] = set()
            for iface in self._source.params.interfaces:
                et = iface.element_type
                if et in seen_types:
                    continue
                seen_types.add(et)
                type_meta = INTERFACE_TYPES.get(et, {})
                type_name = type_meta.get("name", et)
                props = type_meta.get("properties", [])
                labels = type_meta.get("property_labels", {})
                units = type_meta.get("property_units", {})

                if not props:
                    continue

                type_label = QtWidgets.QLabel(f"<b>{type_name}</b>")
                props_layout.addWidget(type_label)

                for prop in props:
                    label = labels.get(prop, prop)
                    unit = units.get(prop, "")
                    value = getattr(iface, prop, None)
                    display = f"{label}"
                    if value is not None and not isinstance(value, bool):
                        display += f"  =  {value}"
                        if unit:
                            display += f" {unit}"
                    cb = QtWidgets.QCheckBox(display)
                    cb.setChecked(True)
                    key = f"{et}:{prop}"
                    self._property_checks[key] = cb
                    props_layout.addWidget(cb)

        layout.addWidget(props_group)

        # --- Buttons ---
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Apply
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        apply_btn = btn_box.button(QtWidgets.QDialogButtonBox.StandardButton.Apply)
        if apply_btn is not None:
            apply_btn.clicked.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _separator() -> QtWidgets.QFrame:
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        return sep

    def _get_targets(self) -> list[ComponentItem]:
        """Return the list of target items based on current scope selection."""
        if self._rb_category.isChecked():
            cat = (self._source.params.category or "").lower()
            return [
                item
                for item in self._all_items
                if (item.params.category or "").lower() == cat
            ]
        if self._rb_selected.isChecked():
            return [item for item in self._all_items if item.isSelected()]
        return list(self._all_items)

    def _update_count(self):
        targets = self._get_targets()
        self._count_label.setText(f"Affects <b>{len(targets)}</b> component(s)")

    # ------------------------------------------------------------------
    # Public result accessors (call after exec() == Accepted)
    # ------------------------------------------------------------------

    def get_targets(self) -> list[ComponentItem]:
        return self._get_targets()

    def get_checked_properties(self) -> dict[str, bool]:
        """Return {key: True} for every checked property checkbox.

        Keys are either plain param names (e.g. ``"object_height_mm"``) or
        ``"element_type:property_name"`` for interface-level properties.
        """
        return {key: cb.isChecked() for key, cb in self._property_checks.items()}
