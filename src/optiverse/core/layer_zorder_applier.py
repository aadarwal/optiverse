"""Apply scene z-values from the authoritative LayerTreeState.

This is the only place that should write QGraphicsItem.setZValue() based on layer ordering.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from .layer_tree_state import LayerTreeState


class LayerZOrderApplier(QtCore.QObject):
    """Keeps QGraphicsScene item z-values in sync with LayerTreeState."""

    zValuesApplied = QtCore.pyqtSignal()

    def __init__(
        self,
        layer_state: LayerTreeState,
        scene: QtWidgets.QGraphicsScene,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent)
        self._layer_state = layer_state
        self._scene = scene
        self._layer_state.changed.connect(self.refresh)

    def refresh(self) -> None:
        order = self._layer_state.get_all_items_in_order()
        uuid_to_item: dict[str, QtWidgets.QGraphicsItem] = {}
        for item in self._scene.items():
            if hasattr(item, "item_uuid"):
                uuid_to_item[item.item_uuid] = item

        total = len(order)
        for i, uuid in enumerate(order):
            if it := uuid_to_item.get(uuid):
                it.setZValue(total - 1 - i)

        self.zValuesApplied.emit()


