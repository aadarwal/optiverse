"""Tests for applying component records to placed canvas items (batch UI is manual / CI GUI)."""

import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6 import QtWidgets  # noqa: F401

    HAVE_PYQT6 = True
except ImportError:
    HAVE_PYQT6 = False


@pytest.mark.skipif(not HAVE_PYQT6, reason="PyQt6 not available")
def test_normalized_component_name():
    from optiverse.ui.views.component_canvas_sync import normalized_component_name

    assert normalized_component_name(None) == ""
    assert normalized_component_name("") == ""
    assert normalized_component_name("  Foo  ") == "Foo"


@pytest.mark.skipif(not HAVE_PYQT6, reason="PyQt6 not available")
def test_apply_record_to_component_item_updates_definition():
    from optiverse.core.interface_definition import InterfaceDefinition
    from optiverse.core.models import ComponentParams, ComponentRecord
    from optiverse.services.storage_service import StorageService
    from optiverse.ui.views.component_canvas_sync import apply_record_to_component_item

    iface = InterfaceDefinition(
        x1_mm=-5.0,
        y1_mm=0.0,
        x2_mm=5.0,
        y2_mm=0.0,
        element_type="mirror",
    )
    params = ComponentParams(
        name="Test",
        object_height_mm=40.0,
        interfaces=[iface],
        notes="old",
        category="mirrors",
    )
    item = MagicMock()
    item.params = params
    item._update_geom = MagicMock()
    item._maybe_attach_sprite = MagicMock()
    item.edited = MagicMock()
    item.edited.emit = MagicMock()

    new_iface = InterfaceDefinition(
        x1_mm=-1.0,
        y1_mm=0.0,
        x2_mm=1.0,
        y2_mm=0.0,
        element_type="lens",
        efl_mm=50.0,
    )
    rec = ComponentRecord(
        name="Test",
        image_path="",
        object_height_mm=55.0,
        interfaces=[new_iface],
        category="lenses",
        notes="new notes",
    )
    settings = StorageService().settings_service
    apply_record_to_component_item(item, rec, settings)

    assert params.notes == "new notes"
    assert params.object_height_mm == 55.0
    assert params.category == "lenses"
    assert len(params.interfaces) == 1
    assert params.interfaces[0].element_type == "lens"
    item._update_geom.assert_called_once()
    item._maybe_attach_sprite.assert_called_once()
    item.edited.emit.assert_called_once()
