"""Custom tree view for the layer panel with keyboard handling.

Provides layer-specific keyboard shortcuts and serves as an extensibility
point for future input handling customizations.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets


class KeyboardLayerTreeView(QtWidgets.QTreeView):
    """Tree view with custom keyboard handling for layer operations.

    This subclass of QTreeView provides:
    - Delete/Backspace key handling for removing selected items/groups
    - Extensibility point for future keyboard shortcuts (e.g., Ctrl+G for grouping)

    The class emits signals rather than performing actions directly,
    allowing the parent LayerPanel to handle the actual operations
    with proper undo/redo support.

    Signals:
        deleteKeyPressed: Emitted when Delete or Backspace is pressed
                         (only when not in editing mode)
    """

    deleteKeyPressed = QtCore.pyqtSignal()

    def keyPressEvent(self, event: QtGui.QKeyEvent | None) -> None:
        """Handle key press events with layer-specific shortcuts.

        Args:
            event: The key event to process
        """
        if event is None:
            return super().keyPressEvent(event)

        # Handle delete keys (when not editing an item name)
        if event.key() in (QtCore.Qt.Key.Key_Delete, QtCore.Qt.Key.Key_Backspace):
            if self.state() != QtWidgets.QAbstractItemView.State.EditingState:
                self.deleteKeyPressed.emit()
                event.accept()
                return

        super().keyPressEvent(event)

