from __future__ import annotations

from PyQt6 import QtCore

from optiverse.core.layer_tree_state import LayerTreeState
from optiverse.ui.models.layer_item_model import LayerItemModel


def test_layer_item_model_stale_indexes_return_safe_defaults():
    """
    Model indexes can outlive a tree change (Qt keeps QModelIndex objects around).
    We store (uuid, generation) in internalPointer() so stale indexes are treated as invalid.
    """
    # Use QCoreApplication to avoid requiring GUI platform plugins in headless environments.
    _app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    st = LayerTreeState()
    st.add_item("A", emit=False)
    gid = st.create_group("G", emit=False)
    st.move_item_to_group("A", gid, emit=False)
    st.changed.emit()

    m = LayerItemModel()
    m.set_context(scene=None, layer_state=st, undo_stack=None)

    # Capture an index under the current generation
    root_idx = m.index(0, 0, QtCore.QModelIndex())
    assert root_idx.isValid()
    assert m.rowCount(root_idx) == 1

    # Mutate state (generation bumps); old index is now stale
    st.rename_group(gid, "G2", emit=True)

    # Stale index should not crash and should appear empty/invalid to the model
    assert m.rowCount(root_idx) == 0
    assert m.data(root_idx, int(QtCore.Qt.ItemDataRole.DisplayRole)) is None
    assert not m.parent(root_idx).isValid()


