"""Delegate for rendering layer rows (icons + text) in a QTreeView.

Replaces QWidget-per-row (`setIndexWidget` / `setItemWidget`) with custom painting
and hit-tested click handling. This avoids widget loss during drag/drop.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from ..models.layer_item_model import (
    IS_AUTOLABEL_ROLE,
    IS_GROUP_ROLE,
    IS_LINKED_ROLE,
    LOCKED_ROLE,
    VISIBLE_ROLE,
)
from ..widgets.constants import LAYER_ITEM_MARGIN, LAYER_ITEM_SPACING, TOGGLE_BUTTON_SIZE, Icons


class LayerItemDelegate(QtWidgets.QStyledItemDelegate):
    """Paints visibility/lock icons and the item/group label; handles icon clicks."""

    def paint(  # type: ignore[override]
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        painter.save()
        try:
            opt = QtWidgets.QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)

            # Let Qt's style draw the background (respects QSS for selection/hover/normal)
            # This ensures consistent painting across the entire row including indentation
            style = opt.widget.style() if opt.widget else QtWidgets.QApplication.style()
            if style:
                style.drawPrimitive(
                    QtWidgets.QStyle.PrimitiveElement.PE_PanelItemViewItem,
                    opt,
                    painter,
                    opt.widget,
                )

            # Determine text color based on selection state
            is_selected = bool(opt.state & QtWidgets.QStyle.StateFlag.State_Selected)
            text_color_role = (
                QtGui.QPalette.ColorRole.HighlightedText
                if is_selected
                else QtGui.QPalette.ColorRole.Text
            )

            rect = opt.rect.adjusted(LAYER_ITEM_MARGIN, 0, -LAYER_ITEM_MARGIN, 0)
            is_group = bool(index.data(IS_GROUP_ROLE))
            is_autolabel = bool(index.data(IS_AUTOLABEL_ROLE))

            # Icon rects
            vis_rect, lock_rect, folder_rect, text_rect = self._layout_rects(rect, is_group)

            # Dimmed opacity for autolabel rows
            if is_autolabel and not is_selected:
                painter.setOpacity(0.55)

            # Determine icon states
            visible = bool(index.data(VISIBLE_ROLE))
            locked = bool(index.data(LOCKED_ROLE))
            vis_text = Icons.VISIBLE if visible else Icons.HIDDEN
            lock_text = Icons.LOCKED if locked else Icons.UNLOCKED

            # Draw icons with appropriate color for selection state
            self._draw_centered_text(painter, vis_rect, vis_text, opt.palette, text_color_role)
            self._draw_centered_text(painter, lock_rect, lock_text, opt.palette, text_color_role)
            if is_group:
                is_linked = bool(index.data(IS_LINKED_ROLE))
                folder_icon = Icons.LINK if is_linked else Icons.FOLDER
                self._draw_centered_text(
                    painter, folder_rect, folder_icon, opt.palette, text_color_role
                )

            # Draw label (italic for autolabels)
            label = str(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "")
            if is_autolabel:
                font = painter.font()
                font.setItalic(True)
                painter.setFont(font)
            painter.setPen(opt.palette.color(text_color_role))
            painter.drawText(
                text_rect,
                int(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft),
                label,
            )
        finally:
            painter.restore()

    def editorEvent(  # type: ignore[override]
        self,
        event: QtCore.QEvent,
        model: QtCore.QAbstractItemModel,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> bool:
        """Handle mouse events on icons; only allow editing on text area double-click.

        This follows the Qt delegate pattern: intercept events in icon regions to
        toggle visibility/lock on press and consume double-clicks to prevent the
        edit trigger from activating. Double-clicks on the text area pass through
        to Qt's default handling, which opens the inline editor.
        """
        # Only handle left mouse button press/double-click
        if event.type() not in (
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QEvent.Type.MouseButtonDblClick,
        ):
            return super().editorEvent(event, model, option, index)

        mev = event  # type: ignore[assignment]
        if (
            not isinstance(mev, QtGui.QMouseEvent)
            or mev.button() != QtCore.Qt.MouseButton.LeftButton
        ):
            return super().editorEvent(event, model, option, index)

        rect = option.rect.adjusted(LAYER_ITEM_MARGIN, 0, -LAYER_ITEM_MARGIN, 0)
        is_group = bool(index.data(IS_GROUP_ROLE))
        vis_rect, lock_rect, folder_rect, _ = self._layout_rects(rect, is_group)
        pos = mev.position().toPoint()
        is_press = event.type() == QtCore.QEvent.Type.MouseButtonPress

        # Visibility icon - toggle on press, consume double-click
        if vis_rect.contains(pos):
            if is_press:
                model.setData(index, not bool(index.data(VISIBLE_ROLE)), int(VISIBLE_ROLE))
            return True

        # Lock icon - toggle on press, consume double-click
        if lock_rect.contains(pos):
            if is_press:
                new_locked = not bool(index.data(LOCKED_ROLE))
                view = option.widget
                sm = (
                    view.selectionModel()
                    if isinstance(view, QtWidgets.QAbstractItemView)
                    else None
                )
                selected = sm.selectedRows(0) if sm else []
                if len(selected) > 1 and index in selected:
                    from ..models.layer_item_model import LayerItemModel

                    if isinstance(model, LayerItemModel):
                        model.toggle_locked_for_indexes(selected, new_locked)
                    else:
                        model.setData(index, new_locked, int(LOCKED_ROLE))
                else:
                    model.setData(index, new_locked, int(LOCKED_ROLE))
            return True

        # Folder icon - consume all clicks (no action, prevents edit)
        if is_group and folder_rect.contains(pos):
            return True

        # Text area - let Qt handle (select on click, edit on double-click)
        return super().editorEvent(event, model, option, index)

    def sizeHint(
        self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex
    ) -> QtCore.QSize:
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), TOGGLE_BUTTON_SIZE + 2))
        return size

    def updateEditorGeometry(
        self,
        editor: QtWidgets.QWidget | None,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        """Position the editor in the text area (after the icons)."""
        if editor is None:
            return
        rect = option.rect.adjusted(LAYER_ITEM_MARGIN, 0, -LAYER_ITEM_MARGIN, 0)
        is_group = bool(index.data(IS_GROUP_ROLE))
        _, _, _, text_rect = self._layout_rects(rect, is_group)
        editor.setGeometry(text_rect)

    def _layout_rects(
        self, rect: QtCore.QRect, is_group: bool
    ) -> tuple[QtCore.QRect, QtCore.QRect, QtCore.QRect, QtCore.QRect]:
        x = rect.x()
        y = rect.y()
        h = rect.height()
        btn = TOGGLE_BUTTON_SIZE

        vis_rect = QtCore.QRect(x, y + (h - btn) // 2, btn, btn)
        x = vis_rect.right() + 1 + LAYER_ITEM_SPACING
        lock_rect = QtCore.QRect(x, y + (h - btn) // 2, btn, btn)
        x = lock_rect.right() + 1 + LAYER_ITEM_SPACING
        folder_rect = QtCore.QRect(x, y + (h - btn) // 2, btn, btn) if is_group else QtCore.QRect()
        if is_group:
            x = folder_rect.right() + 1 + LAYER_ITEM_SPACING
        text_rect = QtCore.QRect(x + 4, rect.y(), rect.right() - x - 4, rect.height())
        return vis_rect, lock_rect, folder_rect, text_rect

    def _draw_centered_text(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        text: str,
        palette: QtGui.QPalette,
        color_role: QtGui.QPalette.ColorRole = QtGui.QPalette.ColorRole.Text,
    ) -> None:
        painter.setPen(palette.color(color_role))
        painter.drawText(rect, int(QtCore.Qt.AlignmentFlag.AlignCenter), text)


