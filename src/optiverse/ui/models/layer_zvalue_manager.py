"""Layer Z-Value Manager - assigns z-values to scene items based on model order.

This manager listens to LayerTreeModel changes and applies z-values to scene items.
Z-values are OUTPUT of the model, not input.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6 import QtCore, QtWidgets

if TYPE_CHECKING:
    from .layer_tree_model import LayerTreeModel


# Offset for rays above their source (keeps source icon visible)
RAY_Z_OFFSET = 0.1


class LayerZValueManager(QtCore.QObject):
    """
    Manages z-values of scene items based on layer model order.
    
    Listens to LayerTreeModel.structureChanged and applies z-values to scene items.
    
    Signals:
        zValuesApplied: Emitted after z-values are applied (for ray retrace)
    """
    
    zValuesApplied = QtCore.pyqtSignal()
    
    def __init__(
        self,
        model: LayerTreeModel,
        scene: QtWidgets.QGraphicsScene,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent)
        self._model = model
        self._scene = scene
        self._uuid_to_item: dict[str, QtWidgets.QGraphicsItem] = {}
        
        # Connect to model
        self._model.structureChanged.connect(self._on_structure_changed)
    
    def _on_structure_changed(self) -> None:
        """Handle model structure change - apply z-values."""
        self._rebuild_cache()
        self._apply_z_values()
        self.zValuesApplied.emit()
    
    def _rebuild_cache(self) -> None:
        """Rebuild UUID to item cache from scene."""
        self._uuid_to_item.clear()
        for item in self._scene.items():
            if hasattr(item, "item_uuid"):
                self._uuid_to_item[item.item_uuid] = item
    
    def _apply_z_values(self) -> None:
        """Apply z-values to scene items based on model order."""
        items_in_order = self._model.get_all_items_in_order()
        total = len(items_in_order)
        
        for i, uuid in enumerate(items_in_order):
            if item := self._uuid_to_item.get(uuid):
                # i=0 (top of list) gets highest z-value
                # i=total-1 (bottom of list) gets z=0
                z_value = total - 1 - i
                item.setZValue(z_value)
    
    def get_z_value_for_source(self, source_uuid: str) -> float:
        """
        Get the z-value for rays from a source.
        
        Rays are rendered slightly above their source.
        
        Args:
            source_uuid: Source item UUID
            
        Returns:
            Z-value for rays (source z-value + offset)
        """
        if item := self._uuid_to_item.get(source_uuid):
            return item.zValue() + RAY_Z_OFFSET
        return RAY_Z_OFFSET
    
    def refresh(self) -> None:
        """Force refresh of z-values (e.g., after scene changes)."""
        self._rebuild_cache()
        self._apply_z_values()


