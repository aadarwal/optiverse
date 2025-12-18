"""Delegate for rendering layer rows (icons + text) in a QTreeView.

Replaces QWidget-per-row (`setIndexWidget` / `setItemWidget`) with custom painting
and hit-tested click handling. This avoids widget loss during drag/drop.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from ..models.layer_item_model import (
    IS_GROUP_ROLE,
    LOCKED_ROLE,
    VISIBLE_ROLE,
)
from ..widgets.constants import LAYER_ITEM_MARGIN, LAYER_ITEM_SPACING, TOGGLE_BUTTON_SIZE, Icons


class LayerItemDelegate(QtWidgets.QStyledItemDelegate):
    """Paints visibility/lock icons and the item/group label; handles icon clicks."""

    # Selection background color (matches dark_theme.qss LayerTreeView::item:selected)
    SELECTION_BG_COLOR = QtGui.QColor(0x3d, 0x5a, 0x80)  # #3d5a80

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        painter.save()
        try:
            opt = QtWidgets.QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)

            # Check if this item is marked as selected
            is_selected = bool(opt.state & QtWidgets.QStyle.StateFlag.State_Selected)

            # Draw background - manually handle selection since Qt stylesheet
            # may not work with custom delegate
            if is_selected:
                painter.fillRect(opt.rect, self.SELECTION_BG_COLOR)
            else:
                # Let style draw default background for non-selected items
                style = opt.widget.style() if opt.widget else QtWidgets.QApplication.style()
                style.drawPrimitive(
                    QtWidgets.QStyle.PrimitiveElement.PE_PanelItemViewItem,
                    opt,
                    painter,
                    opt.widget,
                )

            rect = opt.rect.adjusted(LAYER_ITEM_MARGIN, 0, -LAYER_ITEM_MARGIN, 0)
            is_group = bool(index.data(IS_GROUP_ROLE))

            # Icon rects
            vis_rect, lock_rect, folder_rect, text_rect = self._layout_rects(rect, is_group)

            # Determine icon states
            visible = bool(index.data(VISIBLE_ROLE))
            locked = bool(index.data(LOCKED_ROLE))
            vis_text = Icons.VISIBLE if visible else Icons.HIDDEN
            lock_text = Icons.LOCKED if locked else Icons.UNLOCKED

            # Draw icons
            self._draw_centered_text(painter, vis_rect, vis_text, opt.palette)
            self._draw_centered_text(painter, lock_rect, lock_text, opt.palette)
            if is_group:
                self._draw_centered_text(painter, folder_rect, Icons.FOLDER, opt.palette)

            # Draw label
            label = str(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "")
            painter.setPen(opt.palette.color(QtGui.QPalette.ColorRole.Text))
            painter.drawText(
                text_rect,
                int(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft),
                label,
            )
        finally:
            painter.restore()

    def editorEvent(
        self,
        event: QtCore.QEvent,
        model: QtCore.QAbstractItemModel,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> bool:
        if event.type() == QtCore.QEvent.Type.MouseButtonPress:
            mev = event  # type: ignore[assignment]
            if (
                isinstance(mev, QtGui.QMouseEvent)
                and mev.button() == QtCore.Qt.MouseButton.LeftButton
            ):
                rect = option.rect.adjusted(LAYER_ITEM_MARGIN, 0, -LAYER_ITEM_MARGIN, 0)
                is_group = bool(index.data(IS_GROUP_ROLE))
                vis_rect, lock_rect, _, _ = self._layout_rects(rect, is_group)
                pos = mev.position().toPoint()
                if vis_rect.contains(pos):
                    current = bool(index.data(VISIBLE_ROLE))
                    return bool(model.setData(index, not current, int(VISIBLE_ROLE)))
                if lock_rect.contains(pos):
                    current = bool(index.data(LOCKED_ROLE))
                    return bool(model.setData(index, not current, int(LOCKED_ROLE)))
        return super().editorEvent(event, model, option, index)

    def sizeHint(
        self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex
    ) -> QtCore.QSize:
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), TOGGLE_BUTTON_SIZE + 2))
        return size

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
    ) -> None:
        painter.setPen(palette.color(QtGui.QPalette.ColorRole.Text))
        painter.drawText(rect, int(QtCore.Qt.AlignmentFlag.AlignCenter), text)


