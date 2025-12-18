"""Layer panel widget for managing scene items by z-order.

Uses Qt's Model/View architecture:
- LayerItemModel: tree structure + drag/drop
- LayerItemDelegate: paints icons + text, handles click toggles
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from PyQt6 import QtCore, QtGui, QtWidgets

from ...core.layer_tree_state import LayerTreeState
from ...core.undo_commands import CreateGroupCommand, DeleteGroupCommand
from ..delegates import LayerItemDelegate
from ..models import LayerItemModel
from .constants import Icons

if TYPE_CHECKING:
    from ...core.undo_stack import UndoStack

from ..models.layer_item_model import GROUP_UUID_ROLE, IS_GROUP_ROLE, ITEM_UUID_ROLE


class LayerTreeView(QtWidgets.QTreeView):
    """Tree view with delete key handling."""

    deleteKeyPressed = QtCore.pyqtSignal()

    def keyPressEvent(self, event: QtGui.QKeyEvent | None) -> None:
        if event and event.key() in (QtCore.Qt.Key.Key_Delete, QtCore.Qt.Key.Key_Backspace):
            if self.state() != QtWidgets.QAbstractItemView.State.EditingState:
                self.deleteKeyPressed.emit()
                event.accept()
                return
        super().keyPressEvent(event)


class LayerPanel(QtWidgets.QWidget):
    """Layer panel for managing scene items by z-order."""

    selectionChanged = QtCore.pyqtSignal(list)
    zOrderChanged = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._scene: QtWidgets.QGraphicsScene | None = None
        self._layer_state: LayerTreeState | None = None

        self._model = LayerItemModel(self)
        self._model.orderChanged.connect(self._on_model_order_changed)

        # Debounce timers
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh)

        self._sync_timer = QtCore.QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._do_sync_from_scene_selection)

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header
        header = QtWidgets.QWidget()
        h_layout = QtWidgets.QHBoxLayout(header)
        h_layout.setContentsMargins(8, 8, 8, 4)

        title = QtWidgets.QLabel("Layers")
        title.setObjectName("layerPanelTitle")
        h_layout.addWidget(title)
        h_layout.addStretch()

        for icon, tooltip, callback in [
            (Icons.FOLDER_ADD, "Group selected items", self._group_selected),
            (Icons.FOLDER_REMOVE, "Ungroup selected group", self._ungroup_selected),
        ]:
            btn = QtWidgets.QToolButton()
            btn.setText(icon)
            btn.setToolTip(tooltip)
            btn.clicked.connect(callback)
            h_layout.addWidget(btn)

        layout.addWidget(header)

        # Tree view
        self._tree = LayerTreeView()
        self._tree.setModel(self._model)
        self._tree.setItemDelegate(LayerItemDelegate(self._tree))
        self._tree.setHeaderHidden(True)
        self._tree.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self._tree.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        self._tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tree.setIndentation(16)
        self._tree.setRootIsDecorated(True)
        self._tree.setAnimated(True)
        self._tree.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._tree.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked)

        if sm := self._tree.selectionModel():
            sm.selectionChanged.connect(self._on_selection_changed)

        self._tree.deleteKeyPressed.connect(self._delete_selected)
        self._tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.expanded.connect(lambda idx: self._set_group_collapsed(idx, False))
        self._tree.collapsed.connect(lambda idx: self._set_group_collapsed(idx, True))
        layout.addWidget(self._tree, 1)

        # Z-order buttons
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.setContentsMargins(8, 4, 8, 8)
        for text, tooltip, op in [
            ("↑ Up", "Bring forward", "bring_forward"),
            ("↓ Down", "Send backward", "send_backward"),
        ]:
            btn = QtWidgets.QPushButton(text)
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda _, o=op: self._apply_z_order(o))
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)

    def set_scene(self, scene: QtWidgets.QGraphicsScene) -> None:
        self._scene = scene
        self._model.set_context(
            scene=scene, layer_state=self._layer_state, undo_stack=self._get_undo_stack()
        )

    @property
    def model(self) -> LayerItemModel:
        return self._model

    def set_layer_state(self, layer_state: LayerTreeState) -> None:
        self._layer_state = layer_state
        layer_state.changed.connect(self.refresh)
        self._model.set_context(
            scene=self._scene, layer_state=layer_state, undo_stack=self._get_undo_stack()
        )

    def _get_undo_stack(self) -> UndoStack | None:
        if not self._scene or not (views := self._scene.views()):
            return None
        window = views[0].window()
        return cast("UndoStack | None", getattr(window, "undo_stack", None))

    def cleanup(self) -> None:
        """Clean up before shutdown to prevent accessing deleted objects."""
        self._refresh_timer.stop()
        self._sync_timer.stop()
        self._model.cleanup()

    # --- Refresh ---

    def refresh(self) -> None:
        """Debounced refresh."""
        self._refresh_timer.stop()
        self._sync_timer.stop()
        self._refresh_timer.start(100)

    def _do_refresh(self) -> None:
        if not self._scene:
            return
        self._model.set_context(
            scene=self._scene,
            layer_state=self._layer_state,
            undo_stack=self._get_undo_stack(),
        )
        self._apply_group_collapsed_state()
        self._do_sync_from_scene_selection()

    def _apply_group_collapsed_state(self) -> None:
        """Expand/collapse groups based on LayerTreeState."""
        if not self._layer_state:
            return
        self._tree.blockSignals(True)
        try:
            self._walk_and_apply_collapsed(QtCore.QModelIndex())
        finally:
            self._tree.blockSignals(False)

    def _walk_and_apply_collapsed(self, parent: QtCore.QModelIndex) -> None:
        for r in range(self._model.rowCount(parent)):
            idx = self._model.index(r, 0, parent)
            if not idx.isValid():
                continue
            if bool(idx.data(IS_GROUP_ROLE)):
                group_uuid = cast(str, idx.data(GROUP_UUID_ROLE))
                node = (
                    self._layer_state.get_node(group_uuid)
                    if group_uuid and self._layer_state
                    else None
                )
                collapsed = bool(getattr(node, "collapsed", False)) if node else False
                self._tree.setExpanded(idx, not collapsed)
            self._walk_and_apply_collapsed(idx)

    def _set_group_collapsed(self, idx: QtCore.QModelIndex, collapsed: bool) -> None:
        if not self._layer_state or not idx.isValid() or not bool(idx.data(IS_GROUP_ROLE)):
            return
        if group_uuid := idx.data(GROUP_UUID_ROLE):
            self._layer_state.set_group_collapsed(str(group_uuid), collapsed, emit=True)

    # --- Z-Order ---

    def _apply_z_order(self, operation: str) -> None:
        if not self._scene or not self._layer_state:
            return
        uuids = [
            item.item_uuid for item in self._scene.selectedItems() if hasattr(item, "item_uuid")
        ]
        if uuids:
            self._layer_state.apply_z_order_operation(uuids, operation)

    def _on_model_order_changed(self) -> None:
        self.zOrderChanged.emit()

    # --- Selection ---

    def _on_selection_changed(
        self,
        _sel: QtCore.QItemSelection | None = None,
        _desel: QtCore.QItemSelection | None = None,
    ) -> None:
        if not self._scene:
            return
        selected: list[str] = []
        if sm := self._tree.selectionModel():
            for idx in sm.selectedRows(0):
                selected.extend(self._model.item_uuids_under(idx))
        self._scene.clearSelection()
        for item in self._scene.items():
            if hasattr(item, "item_uuid") and item.item_uuid in selected:
                item.setSelected(True)
        self.selectionChanged.emit(selected)

    def sync_from_scene_selection(self) -> None:
        """Sync layer panel selection from scene (debounced)."""
        if self._refresh_timer.isActive():
            return
        self._sync_timer.stop()
        self._sync_timer.start(50)

    def _do_sync_from_scene_selection(self) -> None:
        if not self._scene:
            return
        uuids = {
            item.item_uuid for item in self._scene.selectedItems() if hasattr(item, "item_uuid")
        }
        sm = self._tree.selectionModel()
        if not sm:
            return
        sm.blockSignals(True)
        try:
            sm.clearSelection()
            if uuids:
                self._select_by_uuid(uuids, QtCore.QModelIndex())
        finally:
            sm.blockSignals(False)
        self._tree.viewport().update()

    def _select_by_uuid(self, uuids: set[str], parent: QtCore.QModelIndex) -> None:
        sm = self._tree.selectionModel()
        if not sm:
            return
        for r in range(self._model.rowCount(parent)):
            idx = self._model.index(r, 0, parent)
            if not idx.isValid():
                continue
            if not bool(idx.data(IS_GROUP_ROLE)):
                if idx.data(ITEM_UUID_ROLE) in uuids:
                    sm.select(
                        idx,
                        QtCore.QItemSelectionModel.SelectionFlag.Select
                        | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                    )
            self._select_by_uuid(uuids, idx)

    # --- Actions ---

    def _group_selected(self) -> None:
        if not self._scene or not self._layer_state:
            return
        selected = self._scene.selectedItems()
        if len(selected) < 2:
            QtWidgets.QMessageBox.information(
                self, "Group Items", "Select at least 2 items to group."
            )
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Create Group", "Group name:", text="Group")
        if not ok:
            return
        uuids = [item.item_uuid for item in selected if hasattr(item, "item_uuid")]
        if not uuids:
            return
        cmd = CreateGroupCommand(self._layer_state, name or "Group", uuids, None)
        if undo := self._get_undo_stack():
            undo.push(cmd)
        else:
            cmd.execute()

    def _ungroup_selected(self) -> None:
        if not self._layer_state:
            return
        group_uuid: str | None = None

        # Check if a group is selected in tree
        if sm := self._tree.selectionModel():
            for idx in sm.selectedRows(0):
                if bool(idx.data(IS_GROUP_ROLE)):
                    group_uuid = cast(str, idx.data(GROUP_UUID_ROLE))
                    break

        # Check if selected items share a common group
        if not group_uuid and self._scene:
            groups: set[str] = set()
            for item in self._scene.selectedItems():
                if hasattr(item, "item_uuid"):
                    node = self._layer_state.get_node(item.item_uuid)
                    if node and node.parent and node.parent.is_group():
                        groups.add(node.parent.uuid)
            if len(groups) == 1:
                group_uuid = groups.pop()

        if not group_uuid:
            QtWidgets.QMessageBox.information(self, "Ungroup", "Select a group to ungroup.")
            return

        cmd = DeleteGroupCommand(self._layer_state, group_uuid, keep_items=True)
        if undo := self._get_undo_stack():
            undo.push(cmd)
        else:
            cmd.execute()

    def _delete_selected(self) -> None:
        if not self._scene:
            return
        sm = self._tree.selectionModel()
        if not sm:
            return
        rows = sm.selectedRows(0)
        if not rows:
            return

        from ...core.undo_commands import RemoveItemCommand

        undo = self._get_undo_stack()
        group_uuids: set[str] = set()
        item_uuids: set[str] = set()

        for idx in rows:
            if bool(idx.data(IS_GROUP_ROLE)):
                if gu := idx.data(GROUP_UUID_ROLE):
                    group_uuids.add(str(gu))
            elif iu := idx.data(ITEM_UUID_ROLE):
                item_uuids.add(str(iu))

        for gid in group_uuids:
            if self._layer_state:
                cmd = DeleteGroupCommand(self._layer_state, gid, keep_items=False)
                if undo:
                    undo.push(cmd)
                else:
                    cmd.execute()

        for uid in item_uuids:
            item = next(
                (
                    i
                    for i in self._scene.items()
                    if hasattr(i, "item_uuid") and i.item_uuid == uid
                ),
                None,
            )
            if item:
                if undo:
                    undo.push(RemoveItemCommand(self._scene, item, self._layer_state))
                else:
                    if self._layer_state:
                        self._layer_state.remove_item(uid, emit=True)
                    self._scene.removeItem(item)

        self.refresh()

    def _show_context_menu(self, pos: QtCore.QPoint) -> None:
        idx = self._tree.indexAt(pos)
        menu = QtWidgets.QMenu(self)

        if idx.isValid():
            from ..models.layer_item_model import LOCKED_ROLE, VISIBLE_ROLE

            vis_act = menu.addAction("Toggle Visibility")
            if vis_act:
                vis_act.triggered.connect(lambda: self._toggle_role(idx, VISIBLE_ROLE))
            lock_act = menu.addAction("Toggle Lock")
            if lock_act:
                lock_act.triggered.connect(lambda: self._toggle_role(idx, LOCKED_ROLE))
            menu.addSeparator()

            if bool(idx.data(IS_GROUP_ROLE)):
                if act := menu.addAction("Ungroup"):
                    act.triggered.connect(self._ungroup_selected)
            else:
                if act := menu.addAction("Group with Selected"):
                    act.triggered.connect(self._group_selected)
            menu.addSeparator()
            if act := menu.addAction("Delete"):
                act.triggered.connect(self._delete_selected)

        menu.addSeparator()
        if z_menu := menu.addMenu("Z-Order"):
            for label, op in [
                ("Bring to Front", "bring_to_front"),
                ("Bring Forward", "bring_forward"),
                ("Send Backward", "send_backward"),
                ("Send to Back", "send_to_back"),
            ]:
                if act := z_menu.addAction(label):
                    act.triggered.connect(lambda _, o=op: self._apply_z_order(o))

        if vp := self._tree.viewport():
            menu.exec(vp.mapToGlobal(pos))

    def _toggle_role(self, idx: QtCore.QModelIndex, role: int) -> None:
        current = bool(idx.data(role))
        self._model.setData(idx, not current, role)
        self.refresh()
