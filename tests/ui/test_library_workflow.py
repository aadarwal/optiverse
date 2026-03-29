"""
Tests for the complete UI workflow: dragging components from library,
moving them on the canvas, and rotating them.

This tests:
- Library drag and drop for all standard components
- ItemDragHandler for moving items
- rotation_handler.py for rotating items (Ctrl+drag, group, wheel)
- Complete workflow integration
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from optiverse.core.constants import MIME_OPTICS_COMPONENT
from optiverse.objects import ComponentItem
from optiverse.objects.definitions_loader import load_component_dicts
from tests.helpers.ui_test_helpers import (
    create_main_window,
    get_scene_items_by_type,
)

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def library_components() -> list[dict]:
    """
    Load all standard library component definitions from JSON files.

    Returns:
        List of component dictionaries that can be used for drag/drop tests.
    """
    components = load_component_dicts()
    assert len(components) > 0, "No components found in library"
    return components


@pytest.fixture
def component_by_category(library_components: list[dict]) -> dict[str, list[dict]]:
    """
    Organize library components by category.

    Returns:
        Dictionary mapping category name to list of components.
    """
    by_category: dict[str, list[dict]] = {}
    for comp in library_components:
        category = comp.get("category", "other")
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(comp)
    return by_category


@pytest.fixture
def main_window(qtbot: QtBot):
    """Create a MainWindow for testing."""
    window = create_main_window(qtbot)
    yield window
    # Cleanup
    window.close()


# =============================================================================
# Helper Functions
# =============================================================================


def create_drag_mime_data(component_dict: dict) -> QtCore.QMimeData:
    """Create QMimeData for dragging a component from library."""
    mime_data = QtCore.QMimeData()
    mime_data.setData(
        MIME_OPTICS_COMPONENT, json.dumps(component_dict).encode("utf-8")
    )
    return mime_data


def simulate_component_drop(
    qtbot: QtBot,
    view: QtWidgets.QGraphicsView,
    component_dict: dict,
    drop_pos: QtCore.QPoint,
) -> None:
    """
    Simulate dropping a component from library onto the graphics view.

    Args:
        qtbot: QtBot instance
        view: GraphicsView to drop onto
        component_dict: Component data dictionary
        drop_pos: Position in view coordinates where to drop
    """
    mime_data = create_drag_mime_data(component_dict)

    # Create and process drop event
    drop_event = QtGui.QDropEvent(
        QtCore.QPointF(drop_pos),
        QtCore.Qt.DropAction.CopyAction,
        mime_data,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )

    view.dropEvent(drop_event)
    qtbot.wait(50)  # Allow event processing


def get_component_items(scene: QtWidgets.QGraphicsScene) -> list[ComponentItem]:
    """Get all ComponentItems from the scene."""
    return get_scene_items_by_type(scene, ComponentItem)


# =============================================================================
# Test: Library Component Loading
# =============================================================================


class TestLibraryComponentLoading:
    """Test that library components can be loaded correctly."""

    def test_library_has_components(self, library_components: list[dict]):
        """Library should contain multiple components."""
        assert len(library_components) >= 10, "Expected at least 10 components in library"

    def test_all_components_have_required_fields(self, library_components: list[dict]):
        """All components should have required fields."""
        for comp in library_components:
            assert "name" in comp, f"Component missing 'name': {comp}"
            name = comp.get("name")
            assert "object_height_mm" in comp, f"Component {name} missing 'object_height_mm'"

    def test_components_have_categories(self, component_by_category: dict[str, list[dict]]):
        """Components should be organized into categories."""
        # Check for expected categories
        expected_categories = {"lenses", "mirrors", "beamsplitters"}
        actual_categories = set(component_by_category.keys())
        # At least some expected categories should exist
        assert len(expected_categories & actual_categories) >= 2, (
            f"Expected categories from {expected_categories}, got {actual_categories}"
        )


# =============================================================================
# Test: Library Drag and Drop
# =============================================================================


class TestLibraryDragAndDrop:
    """Test dragging components from library and dropping on canvas."""

    def test_drop_creates_component(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Dropping a component from library should create it on canvas."""
        # Get a lens component
        lens_comp = next(
            (c for c in library_components if "lens" in c.get("category", "").lower()),
            library_components[0],
        )

        initial_count = len(get_component_items(main_window.scene))

        # Simulate drop at center of view
        view = main_window.view
        center = view.viewport().rect().center()
        simulate_component_drop(qtbot, view, lens_comp, center)

        # Verify component was created
        final_count = len(get_component_items(main_window.scene))
        assert final_count == initial_count + 1, "Component should be created after drop"

    def test_dropped_component_has_correct_name(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Dropped component should have the name from library definition."""
        # Pick a specific component
        comp = library_components[0]
        expected_name = comp.get("name", "")

        view = main_window.view
        center = view.viewport().rect().center()
        simulate_component_drop(qtbot, view, comp, center)

        items = get_component_items(main_window.scene)
        assert len(items) >= 1, "Should have at least one component"

        # Check the most recent item has correct name
        dropped_item = items[-1]
        assert dropped_item.params.name == expected_name

    def test_drop_at_specific_position(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Component should be created at the drop position."""
        comp = library_components[0]

        view = main_window.view
        # Drop at a specific view position
        drop_view_pos = QtCore.QPoint(200, 150)
        expected_scene_pos = view.mapToScene(drop_view_pos)

        simulate_component_drop(qtbot, view, comp, drop_view_pos)

        items = get_component_items(main_window.scene)
        dropped_item = items[-1]

        # Position should be near drop point (may be snapped to grid)
        actual_pos = dropped_item.pos()
        assert abs(actual_pos.x() - expected_scene_pos.x()) < 2, "X should match drop"
        assert abs(actual_pos.y() - expected_scene_pos.y()) < 2, "Y should match drop"

    def test_undo_removes_dropped_component(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Undoing after drop should remove the component."""
        comp = library_components[0]

        initial_count = len(get_component_items(main_window.scene))

        view = main_window.view
        center = view.viewport().rect().center()
        simulate_component_drop(qtbot, view, comp, center)

        # Verify component exists
        assert len(get_component_items(main_window.scene)) == initial_count + 1

        # Undo
        main_window.undo_stack.undo()
        qtbot.wait(50)

        # Component should be removed
        assert len(get_component_items(main_window.scene)) == initial_count

    @pytest.mark.parametrize(
        "category",
        ["lenses", "mirrors", "beamsplitters", "waveplates"],
    )
    def test_drop_components_by_category(
        self, qtbot: QtBot, main_window, component_by_category: dict[str, list[dict]], category: str
    ):
        """Test dropping components from each category."""
        if category not in component_by_category:
            pytest.skip(f"No components in category '{category}'")

        comp = component_by_category[category][0]
        initial_count = len(get_component_items(main_window.scene))

        view = main_window.view
        center = view.viewport().rect().center()
        simulate_component_drop(qtbot, view, comp, center)

        final_count = len(get_component_items(main_window.scene))
        assert final_count == initial_count + 1, f"Failed to drop {category} component"


# =============================================================================
# Test: Item Movement
# =============================================================================


class TestItemMovement:
    """Test moving items on the canvas."""

    def test_move_item_updates_position(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Moving an item should update its position."""
        # Drop a component
        comp = library_components[0]
        view = main_window.view
        center = view.viewport().rect().center()
        simulate_component_drop(qtbot, view, comp, center)

        item = get_component_items(main_window.scene)[-1]
        initial_pos = QtCore.QPointF(item.pos())

        # Move the item programmatically
        new_x = initial_pos.x() + 50
        new_y = initial_pos.y() + 30
        item.setPos(new_x, new_y)

        # Verify position changed
        assert abs(item.pos().x() - new_x) < 0.1
        assert abs(item.pos().y() - new_y) < 0.1

    def test_move_item_with_mouse_simulation(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Simulate mouse drag to move item."""
        # Drop a component
        comp = library_components[0]
        view = main_window.view
        drop_pos = QtCore.QPoint(300, 200)
        simulate_component_drop(qtbot, view, comp, drop_pos)

        item = get_component_items(main_window.scene)[-1]
        initial_pos = QtCore.QPointF(item.pos())

        # Select the item
        main_window.scene.clearSelection()
        item.setSelected(True)

        # Create mouse press event at item position
        scene_pos = item.pos()
        press_event = QtWidgets.QGraphicsSceneMouseEvent(
            QtCore.QEvent.Type.GraphicsSceneMousePress
        )
        press_event.setScenePos(scene_pos)
        press_event.setButton(QtCore.Qt.MouseButton.LeftButton)
        press_event.setModifiers(QtCore.Qt.KeyboardModifier.NoModifier)

        # Track position via drag handler
        main_window.drag_handler.handle_mouse_press_at_scene_pos(
            scene_pos, QtCore.Qt.KeyboardModifier.NoModifier
        )

        # Move item
        move_delta = QtCore.QPointF(100, 50)
        item.setPos(initial_pos + move_delta)

        # Release
        main_window.drag_handler.handle_mouse_release()

        # Verify position changed
        assert abs(item.pos().x() - (initial_pos.x() + 100)) < 1
        assert abs(item.pos().y() - (initial_pos.y() + 50)) < 1

    def test_undo_restores_position(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Undoing a move should restore original position."""
        # Drop a component
        comp = library_components[0]
        view = main_window.view
        simulate_component_drop(qtbot, view, comp, view.viewport().rect().center())

        item = get_component_items(main_window.scene)[-1]
        initial_pos = QtCore.QPointF(item.pos())

        # Select and move with undo tracking
        item.setSelected(True)
        main_window.drag_handler.handle_mouse_press_at_scene_pos(
            initial_pos, QtCore.Qt.KeyboardModifier.NoModifier
        )

        # Move to new position
        new_pos = initial_pos + QtCore.QPointF(75, 25)
        item.setPos(new_pos)

        # Release (creates undo command)
        main_window.drag_handler.handle_mouse_release()

        # Verify moved
        assert abs(item.pos().x() - new_pos.x()) < 1
        assert abs(item.pos().y() - new_pos.y()) < 1

        # Undo should restore position
        main_window.undo_stack.undo()
        qtbot.wait(50)

        assert abs(item.pos().x() - initial_pos.x()) < 1
        assert abs(item.pos().y() - initial_pos.y()) < 1

    def test_multi_selection_move(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Moving with multi-selection should move all selected items."""
        # Drop two components at different positions
        view = main_window.view

        simulate_component_drop(
            qtbot, view, library_components[0], QtCore.QPoint(200, 150)
        )
        simulate_component_drop(
            qtbot, view, library_components[0], QtCore.QPoint(400, 150)
        )

        items = get_component_items(main_window.scene)
        assert len(items) >= 2

        item1, item2 = items[-2], items[-1]
        initial_pos1 = QtCore.QPointF(item1.pos())
        initial_pos2 = QtCore.QPointF(item2.pos())

        # Select both items
        main_window.scene.clearSelection()
        item1.setSelected(True)
        item2.setSelected(True)

        # Start drag on item1
        main_window.drag_handler.handle_mouse_press_at_scene_pos(
            initial_pos1, QtCore.Qt.KeyboardModifier.NoModifier
        )

        # Move item1 (primary)
        move_delta = QtCore.QPointF(50, 30)
        item1.setPos(initial_pos1 + move_delta)

        # Update group positions
        main_window.drag_handler.update_group_positions()

        # Release
        main_window.drag_handler.handle_mouse_release()

        # Both items should have moved by same delta
        assert abs((item1.pos().x() - initial_pos1.x()) - 50) < 2
        assert abs((item2.pos().x() - initial_pos2.x()) - 50) < 2


# =============================================================================
# Test: Rotation
# =============================================================================


class TestRotation:
    """Test rotating items."""

    def test_set_rotation_updates_angle(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Setting rotation should update item angle."""
        # Drop a component
        comp = library_components[0]
        view = main_window.view
        simulate_component_drop(qtbot, view, comp, view.viewport().rect().center())

        item = get_component_items(main_window.scene)[-1]
        initial_rotation = item.rotation()

        # Rotate by 45 degrees
        item.setRotation(initial_rotation + 45)

        assert abs(item.rotation() - (initial_rotation + 45)) < 0.1

    def test_rotation_undo(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Undoing rotation should restore original angle."""
        from optiverse.core.undo_commands import RotateItemCommand

        # Drop a component
        comp = library_components[0]
        view = main_window.view
        simulate_component_drop(qtbot, view, comp, view.viewport().rect().center())

        item = get_component_items(main_window.scene)[-1]
        initial_rotation = item.rotation()

        # Rotate with undo command
        new_rotation = initial_rotation + 90
        cmd = RotateItemCommand(item, initial_rotation, new_rotation)
        main_window.undo_stack.push(cmd)

        # Verify rotated
        assert abs(item.rotation() - new_rotation) < 0.1

        # Undo
        main_window.undo_stack.undo()
        qtbot.wait(50)

        # Should be back to original
        assert abs(item.rotation() - initial_rotation) < 0.1

    def test_ctrl_drag_rotation_handler(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Test SingleItemRotationHandler for Ctrl+drag rotation."""
        from optiverse.objects.rotation_handler import SingleItemRotationHandler

        # Drop a component
        comp = library_components[0]
        view = main_window.view
        simulate_component_drop(qtbot, view, comp, view.viewport().rect().center())

        item = get_component_items(main_window.scene)[-1]
        initial_rotation = item.rotation()

        # Create rotation handler
        handler = SingleItemRotationHandler(item)

        # Start rotation at a point offset from center
        start_pos = item.pos() + QtCore.QPointF(50, 0)
        handler.start_rotation(start_pos, initial_rotation)

        assert handler.is_rotating

        # Update rotation by moving mouse
        # Moving 90 degrees around the item should rotate ~90 degrees
        rotated_pos = item.pos() + QtCore.QPointF(0, 50)
        new_rotation = handler.update_rotation(rotated_pos)

        # Should have rotated (exact value depends on geometry)
        assert new_rotation != initial_rotation

        # Apply rotation
        item.setRotation(new_rotation)

        # Finish rotation
        handler.finish_rotation()
        assert not handler.is_rotating

    def test_group_rotation_handler(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Test GroupRotationHandler for rotating multiple items."""
        from optiverse.objects.rotation_handler import GroupRotationHandler

        # Drop two components
        view = main_window.view
        simulate_component_drop(
            qtbot, view, library_components[0], QtCore.QPoint(200, 200)
        )
        simulate_component_drop(
            qtbot, view, library_components[0], QtCore.QPoint(300, 200)
        )

        items = get_component_items(main_window.scene)
        assert len(items) >= 2

        item1, item2 = items[-2], items[-1]
        initial_rot1 = item1.rotation()
        initial_rot2 = item2.rotation()

        # Import BaseObj for type checking
        from optiverse.objects import BaseObj

        base_items = [it for it in [item1, item2] if isinstance(it, BaseObj)]

        # Create group rotation handler
        handler = GroupRotationHandler(base_items)

        # Start rotation
        start_pos = QtCore.QPointF(350, 200)  # Right of center
        handler.start_rotation(start_pos)

        assert handler.is_rotating

        # Rotate by moving mouse (90 degrees CCW)
        rotated_pos = QtCore.QPointF(250, 100)  # Above center
        handler.update_rotation(rotated_pos)

        # Items should have rotated
        assert item1.rotation() != initial_rot1 or item2.rotation() != initial_rot2

        handler.finish_rotation()
        assert not handler.is_rotating

    def test_45_degree_snap(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """Test rotation snapping to 45-degree increments."""
        from optiverse.objects.rotation_handler import SingleItemRotationHandler

        # Drop a component
        comp = library_components[0]
        view = main_window.view
        simulate_component_drop(qtbot, view, comp, view.viewport().rect().center())

        item = get_component_items(main_window.scene)[-1]
        item.setRotation(0)

        handler = SingleItemRotationHandler(item)
        start_pos = item.pos() + QtCore.QPointF(100, 0)
        handler.start_rotation(start_pos, 0)

        # Position that would give ~30 degree rotation
        # With snap_to_45=True, should snap to 45 or 0
        test_pos = item.pos() + QtCore.QPointF(86, 50)  # ~30 degrees
        snapped_rotation = handler.update_rotation(test_pos, snap_to_45=True)

        # Should snap to nearest 45 degree (0 or 45)
        assert snapped_rotation % 45 == 0, f"Rotation {snapped_rotation} not snapped to 45deg"

        handler.finish_rotation()


# =============================================================================
# Test: Complete Workflow
# =============================================================================


class TestCompleteWorkflow:
    """End-to-end workflow tests combining drop, move, rotate, and undo."""

    def test_complete_workflow(
        self, qtbot: QtBot, main_window, library_components: list[dict]
    ):
        """
        Test complete user workflow:
        1. Drop lens from library
        2. Drop mirror from library
        3. Move lens
        4. Select both and rotate
        5. Undo all operations
        """
        view = main_window.view
        scene = main_window.scene

        # Find lens and mirror components
        lens_comp = next(
            (c for c in library_components if "lens" in c.get("category", "").lower()),
            library_components[0],
        )
        mirror_comp = next(
            (c for c in library_components if "mirror" in c.get("category", "").lower()),
            library_components[1] if len(library_components) > 1 else library_components[0],
        )

        initial_item_count = len(get_component_items(scene))

        # Step 1: Drop lens at position A
        pos_a = QtCore.QPoint(200, 200)
        simulate_component_drop(qtbot, view, lens_comp, pos_a)
        assert len(get_component_items(scene)) == initial_item_count + 1
        lens_item = get_component_items(scene)[-1]
        lens_initial_pos = QtCore.QPointF(lens_item.pos())

        # Step 2: Drop mirror at position B
        pos_b = QtCore.QPoint(400, 200)
        simulate_component_drop(qtbot, view, mirror_comp, pos_b)
        assert len(get_component_items(scene)) == initial_item_count + 2

        # Step 3: Move lens to new position
        scene.clearSelection()
        lens_item.setSelected(True)

        main_window.drag_handler.handle_mouse_press_at_scene_pos(
            lens_item.pos(), QtCore.Qt.KeyboardModifier.NoModifier
        )

        new_lens_pos = lens_initial_pos + QtCore.QPointF(50, 50)
        lens_item.setPos(new_lens_pos)

        main_window.drag_handler.handle_mouse_release()

        assert abs(lens_item.pos().x() - new_lens_pos.x()) < 2
        assert abs(lens_item.pos().y() - new_lens_pos.y()) < 2

        # Step 4: Rotate lens
        from optiverse.core.undo_commands import RotateItemCommand

        lens_initial_rot = lens_item.rotation()
        rot_cmd = RotateItemCommand(lens_item, lens_initial_rot, lens_initial_rot + 45)
        main_window.undo_stack.push(rot_cmd)

        assert abs(lens_item.rotation() - (lens_initial_rot + 45)) < 0.1

        # Step 5: Undo operations in reverse order
        # Undo rotation
        main_window.undo_stack.undo()
        qtbot.wait(20)
        assert abs(lens_item.rotation() - lens_initial_rot) < 0.1

        # Undo move
        main_window.undo_stack.undo()
        qtbot.wait(20)
        assert abs(lens_item.pos().x() - lens_initial_pos.x()) < 2

        # Undo mirror drop
        main_window.undo_stack.undo()
        qtbot.wait(20)
        assert len(get_component_items(scene)) == initial_item_count + 1

        # Undo lens drop
        main_window.undo_stack.undo()
        qtbot.wait(20)
        assert len(get_component_items(scene)) == initial_item_count

    def test_workflow_with_all_component_types(
        self, qtbot: QtBot, main_window, component_by_category: dict[str, list[dict]]
    ):
        """Test dropping one component from each category."""
        view = main_window.view
        scene = main_window.scene

        initial_count = len(get_component_items(scene))
        dropped_count = 0

        # Drop one component from each category
        x_offset = 100
        for _category, components in component_by_category.items():
            if not components:
                continue

            comp = components[0]
            drop_pos = QtCore.QPoint(x_offset, 200)
            simulate_component_drop(qtbot, view, comp, drop_pos)
            dropped_count += 1
            x_offset += 100

        # Verify all were created
        final_count = len(get_component_items(scene))
        assert final_count == initial_count + dropped_count

        # Undo all drops
        for _ in range(dropped_count):
            main_window.undo_stack.undo()
            qtbot.wait(10)

        # Should be back to initial state
        assert len(get_component_items(scene)) == initial_count
