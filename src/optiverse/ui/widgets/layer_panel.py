"""Layer panel widget for managing scene items by z-order.

This panel uses Qt's Model/View architecture:
- `LayerItemModel` (`QAbstractItemModel`): tree structure + drag/drop + z-order application
- `LayerItemDelegate` (`QStyledItemDelegate`): paints icons + text, handles click toggles

This replaces the previous `QTreeWidget` + `setItemWidget()` approach, which is fragile
under internal drag/drop and can cause row widgets (icons/text) to disappear.
"""

from __future__ import annotations

import sys
import traceback
from typing import TYPE_CHECKING, Callable, cast

from PyQt6 import QtCore, QtGui, QtWidgets

# Debug flag - set to True for verbose logging
_DEBUG_PANEL = True

def _dbg(msg: str) -> None:
    if _DEBUG_PANEL:
        print(f"[LayerPanel] {msg}", flush=True)

from ...core.layer_tree_state import LayerTreeState
from ...core.undo_commands import (
    CreateGroupCommand,
    DeleteGroupCommand,
)
from ...core.zorder_utils import apply_z_order_change
from ..models import LayerItemModel
from ..delegates import LayerItemDelegate
from .constants import (
    LAYER_ITEM_MARGIN,
    LAYER_ITEM_SPACING,
    TOGGLE_BUTTON_SIZE,
    Icons,
)

if TYPE_CHECKING:
    from ...core.undo_stack import UndoStack

from ..models.layer_item_model import GROUP_UUID_ROLE, IS_GROUP_ROLE, ITEM_UUID_ROLE


class LayerTreeView(QtWidgets.QTreeView):
    """Tree view with delete key handling (DnD handled by the model)."""

    deleteKeyPressed = QtCore.pyqtSignal()

    def keyPressEvent(self, event: QtGui.QKeyEvent | None) -> None:
        if event and event.key() in (QtCore.Qt.Key.Key_Delete, QtCore.Qt.Key.Key_Backspace):
            if self.state() != QtWidgets.QAbstractItemView.State.EditingState:
                self.deleteKeyPressed.emit()
                event.accept()
                return
        super().keyPressEvent(event)


class LayerPanel(QtWidgets.QWidget):
    """
    Main layer panel widget.
    
    Coordinates between the layer tree view and the underlying scene/group state.
    """

    selectionChanged = QtCore.pyqtSignal(list)
    zOrderChanged = QtCore.pyqtSignal()  # Emitted when z-order changes (for retrace)

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._scene: QtWidgets.QGraphicsScene | None = None
        self._layer_state: LayerTreeState | None = None
        
        self._model = LayerItemModel(self)
        self._model.orderChanged.connect(self._on_model_order_changed)
        
        # Initialize debounce timers upfront for reliable timer management
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

        # Tree view (Model/View)
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
        
        # Connect selection model signals - model is never detached so this stays valid
        self._connect_selection_signals()
        
        self._tree.deleteKeyPressed.connect(self._delete_selected)
        self._tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.expanded.connect(lambda idx: self._set_group_collapsed_index(idx, False))
        self._tree.collapsed.connect(lambda idx: self._set_group_collapsed_index(idx, True))
        layout.addWidget(self._tree, 1)

        # Z-order buttons
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.setContentsMargins(8, 4, 8, 8)
        buttons = [
            ("↑ Up", "Bring forward", "bring_forward"),
            ("↓ Down", "Send backward", "send_backward"),
        ]
        for text, tooltip, op in buttons:
            push_btn = QtWidgets.QPushButton(text)
            push_btn.setToolTip(tooltip)
            push_btn.clicked.connect(lambda _, o=op: self._apply_z_order(o))
            btn_layout.addWidget(push_btn)
        layout.addLayout(btn_layout)

    def set_scene(self, scene: QtWidgets.QGraphicsScene) -> None:
        self._scene = scene
        self._model.set_context(scene=scene, layer_state=self._layer_state, undo_stack=self._get_undo_stack())

    @property
    def model(self) -> LayerItemModel:
        """Get the layer model used by the layer panel."""
        return self._model

    def set_layer_state(self, layer_state: LayerTreeState) -> None:
        self._layer_state = layer_state
        # Connect to layer state changes for reactive updates
        layer_state.changed.connect(self.refresh)
        # Initialize model context with the layer state
        self._model.set_context(
            scene=self._scene,
            layer_state=layer_state,
            undo_stack=self._get_undo_stack()
        )

    def _connect_selection_signals(self) -> None:
        """Connect to the current selection model.
        
        Since we never detach/reattach the model (which would destroy the selection model),
        this connection remains valid for the lifetime of the panel.
        """
        sm = self._tree.selectionModel()
        if sm:
            sm.selectionChanged.connect(self._on_selection_changed)

    def _get_undo_stack(self) -> UndoStack | None:
        """Get the undo stack from the main window."""
        if not self._scene:
            return None
        if views := self._scene.views():
            window = views[0].window()
            if window is not None and hasattr(window, "undo_stack"):
                return cast("UndoStack | None", window.undo_stack)
        return None

    def refresh(self) -> None:
        """Debounced refresh - coalesces multiple rapid calls into one."""
        _dbg("refresh() called - stopping timers")
        # Cancel any pending timers to avoid interleaving
        self._refresh_timer.stop()
        self._sync_timer.stop()
        
        # 100ms debounce - waits for rapid signals to settle
        self._refresh_timer.start(100)
        _dbg("refresh() - debounced, waiting 100ms")
    
    def _do_refresh(self) -> None:
        """Actual refresh implementation (called after debounce)."""
        _dbg("_do_refresh() START - timer fired")
        if not self._scene:
            _dbg("_do_refresh() - no scene, returning")
            return
        
        _dbg(f"_do_refresh() - scene has {len(list(self._scene.items()))} items")
        _dbg(f"_do_refresh() - tree.model() is self._model: {self._tree.model() is self._model}")
        _dbg(f"_do_refresh() - selectionModel exists: {self._tree.selectionModel() is not None}")
        
        # Use the model's set_context which calls beginResetModel/endResetModel.
        # This is the correct Qt pattern - do NOT detach/reattach the model as
        # that destroys the selection model and breaks signal connections.
        try:
            _dbg("_do_refresh() - calling model.set_context...")
            self._model.set_context(
                scene=self._scene,
                layer_state=self._layer_state,
                undo_stack=self._get_undo_stack()
            )
            _dbg("_do_refresh() - model.set_context completed")
        except Exception as e:
            _dbg(f"_do_refresh() EXCEPTION in set_context: {e}")
            traceback.print_exc()
            raise
        
        try:
            _dbg("_do_refresh() - applying collapsed state...")
            self._apply_group_collapsed_state()
            _dbg("_do_refresh() - collapsed state applied")
        except Exception as e:
            _dbg(f"_do_refresh() EXCEPTION in _apply_group_collapsed_state: {e}")
            traceback.print_exc()
            raise
        
        # After refresh, sync selection from scene to layer panel
        # (any pending sync was cancelled when refresh started)
        try:
            _dbg("_do_refresh() - syncing selection from scene...")
            self._do_sync_from_scene_selection()
        except Exception as e:
            _dbg(f"_do_refresh() EXCEPTION in selection sync: {e}")
            traceback.print_exc()
            # Don't re-raise - selection sync failure shouldn't break refresh
        
        _dbg("_do_refresh() DONE - returning to event loop")
    

    def _apply_group_collapsed_state(self) -> None:
        """Expand/collapse group nodes based on LayerTreeState node.collapsed."""
        _dbg("_apply_group_collapsed_state() START")
        if not self._layer_state:
            _dbg("_apply_group_collapsed_state - no layer_state")
            return

        # Block signals to prevent recursive refresh loop
        self._tree.blockSignals(True)
        try:
            def walk(parent_idx: QtCore.QModelIndex) -> None:
                rows = self._model.rowCount(parent_idx)
                _dbg(f"_apply_group_collapsed_state walk: parent valid={parent_idx.isValid()}, rows={rows}")
                for r in range(rows):
                    _dbg(f"_apply_group_collapsed_state walk: getting index row={r}")
                    idx = self._model.index(r, 0, parent_idx)
                    if not idx.isValid():
                        _dbg(f"_apply_group_collapsed_state walk: idx invalid, skipping")
                        continue
                    try:
                        is_group = bool(idx.data(IS_GROUP_ROLE))
                        if is_group:
                            group_uuid = cast(str, idx.data(GROUP_UUID_ROLE))
                            node = self._layer_state.get_node(group_uuid) if group_uuid else None
                            collapsed = bool(getattr(node, "collapsed", False)) if node else False
                            _dbg(f"_apply_group_collapsed_state: setExpanded idx row={r}, expanded={not collapsed}")
                            self._tree.setExpanded(idx, not collapsed)
                    except Exception as e:
                        _dbg(f"_apply_group_collapsed_state EXCEPTION at row {r}: {e}")
                        traceback.print_exc()
                        raise
                    walk(idx)

            walk(QtCore.QModelIndex())
            _dbg("_apply_group_collapsed_state() DONE")
        finally:
            self._tree.blockSignals(False)

    def _set_group_collapsed_index(self, idx: QtCore.QModelIndex, collapsed: bool) -> None:
        if not self._layer_state:
            return
        if idx.isValid() and bool(idx.data(IS_GROUP_ROLE)):
            group_uuid = cast(str, idx.data(GROUP_UUID_ROLE))
            if group_uuid:
                self._layer_state.set_group_collapsed(group_uuid, collapsed, emit=True)

    # --- Group Operations ---

    def _on_item_dropped_in_group(self, item_uuid: str, group_uuid: str) -> None:
        # Legacy hook (DnD is handled by LayerItemModel now)
        return

    def _on_item_removed_from_group(self, item_uuid: str) -> None:
        # Legacy hook (DnD is handled by LayerItemModel now)
        return

    def _apply_to_group(self, group_uuid: str, action: Callable) -> None:
        # No longer used (delegate/model handle per-node toggles)
        return

    def _collect_group_uuids(self, group_uuid: str) -> list[str]:
        if not self._layer_state:
            return []
        return self._layer_state.get_group_items_recursive(group_uuid)

    # --- Z-Order ---

    def _apply_z_order(self, operation: str) -> None:
        if not self._scene or not (items := list(self._scene.selectedItems())):
            return
        undo_stack = None
        if views := self._scene.views():
            window = views[0].window()
            if window is not None and hasattr(window, "undo_stack"):
                undo_stack = window.undo_stack
        apply_z_order_change(items, operation, self._scene, undo_stack)

    def _on_model_order_changed(self) -> None:
        """Handle z-order changes (retrace)."""
        self.zOrderChanged.emit()

    # --- Selection Sync ---

    def _on_selection_changed(
        self,
        _selected: QtCore.QItemSelection | None = None,
        _deselected: QtCore.QItemSelection | None = None,
    ) -> None:
        """Handle selection changes in the tree view.
        
        Args are provided by QItemSelectionModel.selectionChanged signal but unused.
        """
        _dbg("_on_selection_changed() called")
        if not self._scene:
            _dbg("_on_selection_changed - no scene")
            return
        selected: list[str] = []
        try:
            if sel := self._tree.selectionModel():
                _dbg(f"_on_selection_changed - getting selected rows...")
                for idx in sel.selectedRows(0):
                    _dbg(f"_on_selection_changed - processing idx row={idx.row()}")
                    selected.extend(self._model.item_uuids_under(idx))
        except Exception as e:
            _dbg(f"_on_selection_changed EXCEPTION: {e}")
            traceback.print_exc()
            return

        self._scene.clearSelection()
        for graphics_item in self._scene.items():
            if hasattr(graphics_item, "item_uuid") and graphics_item.item_uuid in selected:
                graphics_item.setSelected(True)
        self.selectionChanged.emit(selected)

    def sync_from_scene_selection(self) -> None:
        """Sync layer panel selection to match scene selection.
        
        Debounced to avoid issues during rapid model updates.
        If a refresh is pending, skip sync - it will be handled after refresh.
        """
        _dbg("sync_from_scene_selection() called")
        # If a refresh is pending, skip sync - the model may be about to change
        if self._refresh_timer.isActive():
            _dbg("sync_from_scene_selection - skipping, refresh pending")
            return
        
        # Cancel any pending sync timer and reschedule
        self._sync_timer.stop()
        self._sync_timer.start(50)
        _dbg("sync_from_scene_selection - debounced, waiting 50ms")

    def _do_sync_from_scene_selection(self) -> None:
        """Actual implementation of selection sync (called after debounce)."""
        _dbg("_do_sync_from_scene_selection START - timer fired")
        if not self._scene:
            _dbg("_do_sync - no scene, returning")
            return
        
        try:
            uuids = {
                item.item_uuid
                for item in self._scene.selectedItems()
                if hasattr(item, "item_uuid")
            }
        except Exception as e:
            _dbg(f"_do_sync EXCEPTION getting selected items: {e}")
            traceback.print_exc()
            return
            
        sm = self._tree.selectionModel()
        if not sm:
            _dbg("_do_sync - no selection model!")
            return
        
        _dbg(f"_do_sync - selectionModel type: {type(sm).__name__}")
        
        sm.blockSignals(True)
        try:
            _dbg("_do_sync - clearing selection...")
            sm.clearSelection()
            
            if not uuids:
                _dbg("_do_sync - no items selected, cleared layer panel selection")
            else:
                _dbg(f"_do_sync - syncing {len(uuids)} selected items")
                _dbg("_do_sync - selecting by uuid...")
                self._select_indexes_by_uuid(uuids)
            _dbg("_do_sync DONE")
        except Exception as e:
            _dbg(f"_do_sync EXCEPTION during selection: {e}")
            traceback.print_exc()
            raise
        finally:
            sm.blockSignals(False)
        
        # Force viewport repaint since we blocked signals during selection change
        self._tree.viewport().update()

    def _select_indexes_by_uuid(self, uuids: set[str]) -> None:
        _dbg(f"_select_indexes_by_uuid() START with {len(uuids)} uuids")
        if not uuids:
            return
        sm = self._tree.selectionModel()
        if not sm:
            _dbg("_select_indexes_by_uuid - no selection model!")
            return
        
        # Collect valid indexes
        indexes_to_select: list[QtCore.QModelIndex] = []

        def walk(parent_idx: QtCore.QModelIndex) -> None:
            rows = self._model.rowCount(parent_idx)
            for r in range(rows):
                try:
                    idx = self._model.index(r, 0, parent_idx)
                    if not idx.isValid():
                        continue
                    is_group = bool(idx.data(IS_GROUP_ROLE))
                    if not is_group:
                        item_uuid = idx.data(ITEM_UUID_ROLE)
                        if item_uuid in uuids:
                            _dbg(f"_select_indexes_by_uuid: found matching uuid at row {r}")
                            indexes_to_select.append(idx)
                    walk(idx)
                except Exception as e:
                    _dbg(f"_select_indexes_by_uuid EXCEPTION at row {r}: {e}")
                    traceback.print_exc()
                    raise

        walk(QtCore.QModelIndex())
        
        _dbg(f"_select_indexes_by_uuid: selecting {len(indexes_to_select)} indexes")
        # Select each index individually
        for idx in indexes_to_select:
            if idx.isValid():
                try:
                    sm.select(idx, QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows)
                except Exception as e:
                    _dbg(f"_select_indexes_by_uuid EXCEPTION selecting: {e}")
                    traceback.print_exc()
                    raise
        _dbg("_select_indexes_by_uuid() DONE")

    # --- Actions ---

    def _group_selected(self) -> None:
        if not self._scene or not self._layer_state:
            return
        selected = self._scene.selectedItems()
        if len(selected) < 2:
            QtWidgets.QMessageBox.information(
                self, "Group Items", "Please select at least 2 items to group."
            )
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Create Group", "Group name:", text="Group")
        if ok:
            # Collect item UUIDs
            item_uuids = [
                item.item_uuid for item in selected
                if hasattr(item, "item_uuid")
            ]
            if not item_uuids:
                return

            # Create group at root for now (subgroup behavior can be added later if desired)
            parent_group_uuid: str | None = None

            undo_stack = self._get_undo_stack()
            if undo_stack:
                cmd = CreateGroupCommand(
                    self._layer_state,
                    name or "Group",
                    item_uuids,
                    parent_group_uuid,
                )
                undo_stack.push(cmd)
            else:
                CreateGroupCommand(self._layer_state, name or "Group", item_uuids, parent_group_uuid).execute()

    def _ungroup_selected(self) -> None:
        if not self._layer_state:
            return

        group_uuid_to_ungroup: str | None = None

        # First, check if a group is directly selected in the tree
        sm = self._tree.selectionModel()
        if sm:
            for idx in sm.selectedRows(0):
                if bool(idx.data(IS_GROUP_ROLE)):
                    group_uuid_to_ungroup = cast(str, idx.data(GROUP_UUID_ROLE))
                break

        # If no group directly selected, check if selected items belong to a common group
        if not group_uuid_to_ungroup and self._scene and self._layer_state:
            selected_scene_items = self._scene.selectedItems()
            if selected_scene_items:
                groups: set[str] = set()
                for scene_item in selected_scene_items:
                    if hasattr(scene_item, "item_uuid"):
                        node = self._layer_state.get_node(scene_item.item_uuid)
                        if node and node.parent and node.parent.is_group():
                            groups.add(node.parent.uuid)
                # If all selected items are in the same group, ungroup that group
                if len(groups) == 1:
                    group_uuid_to_ungroup = groups.pop()

        if group_uuid_to_ungroup:
            undo_stack = self._get_undo_stack()
            if undo_stack:
                cmd = DeleteGroupCommand(
                    self._layer_state,
                    group_uuid_to_ungroup,
                    keep_items=True,
                )
                undo_stack.push(cmd)
            else:
                DeleteGroupCommand(self._layer_state, group_uuid_to_ungroup, keep_items=True).execute()
            return

        QtWidgets.QMessageBox.information(self, "Ungroup", "Please select a group to ungroup.")

    def _delete_selected(self) -> None:
        if not self._scene:
            return
        sm = self._tree.selectionModel()
        if not sm:
            return
        selected_rows = sm.selectedRows(0)
        if not selected_rows:
            return

        from ...core.undo_commands import RemoveItemCommand

        undo_stack = self._get_undo_stack()

        # Prefer deleting selected groups (they own their items); avoid double-delete.
        selected_group_uuids: set[str] = set()
        selected_item_uuids: set[str] = set()
        for idx in selected_rows:
            if bool(idx.data(IS_GROUP_ROLE)):
                if gu := idx.data(GROUP_UUID_ROLE):
                    selected_group_uuids.add(str(gu))
            else:
                if iu := idx.data(ITEM_UUID_ROLE):
                    selected_item_uuids.add(str(iu))

        # If groups are selected, delete them first.
        for group_uuid in selected_group_uuids:
            if not self._layer_state:
                continue
            if undo_stack:
                undo_stack.push(
                    DeleteGroupCommand(
                        self._layer_state,
                        group_uuid,
                        keep_items=False,
                    )
                )
            else:
                DeleteGroupCommand(self._layer_state, group_uuid, keep_items=False).execute()

        # Delete individual items not covered by selected groups.
        for uuid in selected_item_uuids:
            scene_item = self._find_scene_item_by_uuid(uuid)
            if not scene_item:
                continue
            if undo_stack:
                undo_stack.push(RemoveItemCommand(self._scene, scene_item, self._layer_state))
            else:
                if self._layer_state:
                    self._layer_state.remove_item(uuid, emit=True)
                self._scene.removeItem(scene_item)

        self.refresh()

    def _show_context_menu(self, pos: QtCore.QPoint) -> None:
        idx = self._tree.indexAt(pos)
        menu = QtWidgets.QMenu(self)

        if idx.isValid():
            from ..models.layer_item_model import LOCKED_ROLE, VISIBLE_ROLE

            def toggle_visibility() -> None:
                current = bool(idx.data(VISIBLE_ROLE))
                self._model.setData(idx, not current, int(VISIBLE_ROLE))
                self.refresh()

            def toggle_lock() -> None:
                current = bool(idx.data(LOCKED_ROLE))
                self._model.setData(idx, not current, int(LOCKED_ROLE))
                self.refresh()

            visibility_action = menu.addAction("Toggle Visibility")
            if visibility_action is not None:
                visibility_action.triggered.connect(toggle_visibility)
            lock_action = menu.addAction("Toggle Lock")
            if lock_action is not None:
                lock_action.triggered.connect(toggle_lock)
            menu.addSeparator()

            if bool(idx.data(IS_GROUP_ROLE)):
                ungroup_action = menu.addAction("Ungroup")
                if ungroup_action is not None:
                    ungroup_action.triggered.connect(self._ungroup_selected)
            else:
                group_action = menu.addAction("Group with Selected")
                if group_action is not None:
                    group_action.triggered.connect(self._group_selected)
            menu.addSeparator()
            delete_action = menu.addAction("Delete")
            if delete_action is not None:
                delete_action.triggered.connect(self._delete_selected)

        menu.addSeparator()
        z_menu = menu.addMenu("Z-Order")
        if z_menu is not None:
            for label, op in [
                ("Bring to Front", "bring_to_front"),
                ("Bring Forward", "bring_forward"),
                ("Send Backward", "send_backward"),
                ("Send to Back", "send_to_back"),
            ]:
                z_action = z_menu.addAction(label)
                if z_action is not None:
                    z_action.triggered.connect(lambda _, o=op: self._apply_z_order(o))

        viewport = self._tree.viewport()
        if viewport is not None:
            menu.exec(viewport.mapToGlobal(pos))

    def _find_scene_item_by_uuid(self, uuid: str) -> QtWidgets.QGraphicsItem | None:
        if not self._scene:
            return None
        for it in self._scene.items():
            if hasattr(it, "item_uuid") and it.item_uuid == uuid:
                return it
        return None
