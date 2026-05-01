"""Shared context-menu actions usable by any scene item."""

from __future__ import annotations

from PyQt6 import QtWidgets


def add_export_selected_action(
    menu: QtWidgets.QMenu, scene: QtWidgets.QGraphicsScene | None
) -> None:
    """Append an 'Export Selected as Assembly...' action to *menu*."""
    has_selection = bool(
        scene and any(hasattr(it, "item_uuid") for it in scene.selectedItems())
    )
    menu.addSeparator()
    act = menu.addAction("Export Selected as Assembly\u2026")
    if act is not None:
        act.setEnabled(has_selection)
        act.triggered.connect(lambda: _trigger_export(scene))


def _trigger_export(scene: QtWidgets.QGraphicsScene | None) -> None:
    if scene is None:
        return
    for view in scene.views():
        mw = view.window()
        if mw is not None and hasattr(mw, "file_controller"):
            mw.file_controller.export_selected_as_assembly()
            return
