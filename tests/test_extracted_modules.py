"""
Smoke tests for newly extracted modules.

These tests verify that the extracted modules can be imported
and their classes instantiated without errors.
"""

from __future__ import annotations


class TestExtractedModulesImport:
    """Verify that extracted modules can be imported."""

    def test_import_log_categories(self):
        """Test that LogCategory can be imported."""
        from optiverse.core.log_categories import LogCategory

        assert hasattr(LogCategory, "COLLABORATION")
        assert hasattr(LogCategory, "RAYTRACING")
        assert hasattr(LogCategory, "COPY_PASTE")

    def test_import_layer_zorder(self):
        """Test that z-order utilities can be imported."""
        from optiverse.core.layer_tree_state import LayerTreeState
        from optiverse.core.layer_zorder_applier import LayerZOrderApplier

        assert callable(LayerTreeState)
        assert callable(LayerZOrderApplier)

    def test_import_protocols(self):
        """Test that new protocols can be imported."""
        from optiverse.core.protocols import (
            HasCollaboration,
            HasSettings,
            HasSnapping,
            HasUndoStack,
        )

        # Verify these are runtime checkable protocols
        assert getattr(HasUndoStack, "_is_runtime_protocol", False)
        assert getattr(HasCollaboration, "_is_runtime_protocol", False)
        assert getattr(HasSettings, "_is_runtime_protocol", False)
        assert getattr(HasSnapping, "_is_runtime_protocol", False)

    def test_import_constants(self):
        """Test that MIME type constants are available."""
        from optiverse.core.constants import MIME_OPTICS_COMPONENT

        assert MIME_OPTICS_COMPONENT == "application/x-optics-component"


class TestLogCategory:
    """Test LogCategory class."""

    def test_category_values_are_strings(self):
        """Verify all category values are strings."""
        from optiverse.core.log_categories import LogCategory

        categories = [
            LogCategory.COLLABORATION,
            LogCategory.RAYTRACING,
            LogCategory.FILE_IO,
            LogCategory.COPY_PASTE,
            LogCategory.UI,
            LogCategory.COMPONENT,
            LogCategory.SESSION,
        ]

        for category in categories:
            assert isinstance(category, str)
            assert len(category) > 0


class TestProtocolsAreRuntimeCheckable:
    """Test that protocols work with isinstance."""

    def test_has_undo_stack_protocol(self):
        """Test HasUndoStack protocol can be checked at runtime."""
        from optiverse.core.protocols import HasUndoStack

        # Create a mock object that has undo_stack
        class MockWithUndoStack:
            undo_stack = None

        # Note: Protocol checking requires the attribute to exist
        obj = MockWithUndoStack()
        assert isinstance(obj, HasUndoStack)

    def test_has_settings_protocol(self):
        """Test HasSettings protocol can be checked at runtime."""
        from optiverse.core.protocols import HasSettings

        class MockWithSettings:
            settings = None

        obj = MockWithSettings()
        assert isinstance(obj, HasSettings)


