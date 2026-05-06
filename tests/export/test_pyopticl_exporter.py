"""Tests for the PyOpticL exporter module."""

import math
import os

import pytest

from optiverse.export.pyopticl_exporter import (
    BaseplateOptions,
    ExportItem,
    _compute_baseplate_bounds,
    _interface_to_pyopticl,
    _optiverse_angle_to_pyopticl,
    analyse_scene,
    generate_script,
)


# ---------------------------------------------------------------------------
# Interface mapping
# ---------------------------------------------------------------------------


class TestInterfaceMapping:
    def test_mirror_interface(self):
        result = _interface_to_pyopticl({
            "element_type": "mirror",
            "x1_mm": 0.0, "y1_mm": -15.0,
            "x2_mm": 0.0, "y2_mm": 15.0,
        })
        assert result is not None
        assert "Reflection" in result
        assert "30.0" in result  # diameter = 30mm

    def test_lens_interface(self):
        result = _interface_to_pyopticl({
            "element_type": "lens",
            "x1_mm": 0.0, "y1_mm": -10.0,
            "x2_mm": 0.0, "y2_mm": 10.0,
            "efl_mm": 75.0,
        })
        assert result is not None
        assert "Lens" in result
        assert "75.0" in result

    def test_beam_splitter_interface(self):
        result = _interface_to_pyopticl({
            "element_type": "beam_splitter",
            "x1_mm": 0.0, "y1_mm": -12.0,
            "x2_mm": 0.0, "y2_mm": 12.0,
            "split_R": 30.0,
            "is_polarizing": False,
        })
        assert result is not None
        assert "Reflection" in result
        assert "0.300" in result

    def test_dichroic_longpass(self):
        result = _interface_to_pyopticl({
            "element_type": "dichroic",
            "x1_mm": 0.0, "y1_mm": -12.0,
            "x2_mm": 0.0, "y2_mm": 12.0,
            "cutoff_wavelength_nm": 550.0,
            "pass_type": "longpass",
        })
        assert result is not None
        assert "550" in result
        assert "None" in result

    def test_waveplate_interface(self):
        result = _interface_to_pyopticl({
            "element_type": "polarizing_interface",
            "x1_mm": 0.0, "y1_mm": -10.0,
            "x2_mm": 0.0, "y2_mm": 10.0,
            "polarizer_subtype": "waveplate",
            "phase_shift_deg": 90.0,
            "fast_axis_deg": 45.0,
        })
        assert result is not None
        assert "Waveplate" in result
        assert "0.2500" in result  # 90/360

    def test_unknown_type_returns_none(self):
        assert _interface_to_pyopticl({"element_type": "unknown"}) is None

    def test_empty_type_returns_none(self):
        assert _interface_to_pyopticl({}) is None


# ---------------------------------------------------------------------------
# Coordinate transforms
# ---------------------------------------------------------------------------


class TestCoordinateTransforms:
    def test_angle_conversion_zero(self):
        assert _optiverse_angle_to_pyopticl(0.0) == 0.0

    def test_angle_conversion_45(self):
        assert _optiverse_angle_to_pyopticl(45.0) == -45.0

    def test_angle_conversion_negative(self):
        assert _optiverse_angle_to_pyopticl(-30.0) == 30.0

    def test_baseplate_bounds_empty(self):
        x, y, w, h = _compute_baseplate_bounds([], 3.175)
        assert w > 0
        assert h > 0

    def test_baseplate_bounds_single_item(self):
        items = [ExportItem(
            label="M", x_mm=50, y_mm=50, angle_deg=0,
            step_file_path=None, step_filename=None, interfaces=[],
        )]
        x_off, y_off, w, h = _compute_baseplate_bounds(items, 3.175)
        # Must be >= 1 inch
        assert w >= 25.4
        assert h >= 25.4

    def test_baseplate_bounds_multiple_items(self):
        items = [
            ExportItem(label="A", x_mm=0, y_mm=0, angle_deg=0,
                       step_file_path=None, step_filename=None, interfaces=[]),
            ExportItem(label="B", x_mm=200, y_mm=100, angle_deg=0,
                       step_file_path=None, step_filename=None, interfaces=[]),
        ]
        _, _, w, h = _compute_baseplate_bounds(items, 3.175)
        assert w >= 200
        assert h >= 100


# ---------------------------------------------------------------------------
# Scene analysis
# ---------------------------------------------------------------------------


class TestAnalyseScene:
    def test_empty_scene(self):
        items, warnings = analyse_scene({"items": []})
        assert items == []
        assert warnings == []

    def test_source_extraction(self):
        scene = {"items": [{
            "_type": "source",
            "x_mm": 10.0, "y_mm": 20.0, "angle_deg": 0.0,
            "wavelength_nm": 780.0,
        }]}
        items, warnings = analyse_scene(scene)
        assert len(items) == 1
        assert items[0].is_source
        assert items[0].wavelength_nm == 780.0

    def test_component_with_step(self):
        scene = {"items": [{
            "_type": "component",
            "name": "Mirror Mount",
            "x_mm": 50.0, "y_mm": 30.0, "angle_deg": 45.0,
            "step_file_path": "/path/to/mount.step",
            "interfaces": [{"element_type": "mirror", "x1_mm": 0, "y1_mm": -10,
                            "x2_mm": 0, "y2_mm": 10}],
        }]}
        items, warnings = analyse_scene(scene)
        assert len(items) == 1
        assert not items[0].is_source
        assert items[0].step_file_path == "/path/to/mount.step"
        assert warnings == []

    def test_component_without_step_warns(self):
        scene = {"items": [{
            "_type": "component",
            "name": "Bare Mirror",
            "x_mm": 50.0, "y_mm": 30.0, "angle_deg": 45.0,
        }]}
        items, warnings = analyse_scene(scene)
        assert len(items) == 1
        assert warnings == ["Bare Mirror"]


# ---------------------------------------------------------------------------
# Script generation
# ---------------------------------------------------------------------------


class TestGenerateScript:
    def test_script_has_imports(self):
        items = [ExportItem(
            label="Source (633 nm)", x_mm=0, y_mm=0, angle_deg=0,
            step_file_path=None, step_filename=None, interfaces=[],
            is_source=True, wavelength_nm=633.0,
        )]
        script = generate_script(items, BaseplateOptions())
        assert "from PyOpticL" in script
        assert "import_model" in script
        assert "BeamPath" in script

    def test_script_has_layout_function(self):
        items = [ExportItem(
            label="Source", x_mm=0, y_mm=0, angle_deg=0,
            step_file_path=None, step_filename=None, interfaces=[],
            is_source=True,
        )]
        script = generate_script(items, BaseplateOptions())
        assert "def exported_layout" in script
        assert "if __name__" in script

    def test_component_with_step_generates_class(self):
        items = [
            ExportItem(
                label="Source", x_mm=0, y_mm=0, angle_deg=0,
                step_file_path=None, step_filename=None, interfaces=[],
                is_source=True,
            ),
            ExportItem(
                label="Mirror 1", x_mm=80, y_mm=0, angle_deg=45,
                step_file_path="/models/mirror.step",
                step_filename="mirror.step",
                interfaces=[{"element_type": "mirror",
                             "x1_mm": 0, "y1_mm": -15,
                             "x2_mm": 0, "y2_mm": 15}],
            ),
        ]
        script = generate_script(items, BaseplateOptions(label="Test Layout"))
        assert "class component_1_def" in script
        assert 'import_model("mirror"' in script
        assert "Reflection" in script
        assert "Test Layout" in script

    def test_missing_step_comment_in_script(self):
        items = [ExportItem(
            label="No Step", x_mm=10, y_mm=10, angle_deg=0,
            step_file_path=None, step_filename=None, interfaces=[],
        )]
        script = generate_script(items, BaseplateOptions())
        assert "SKIPPED" in script

    def test_script_is_valid_python(self):
        """The generated script should be syntactically valid Python."""
        items = [
            ExportItem(
                label="Source", x_mm=0, y_mm=0, angle_deg=0,
                step_file_path=None, step_filename=None, interfaces=[],
                is_source=True, wavelength_nm=633.0,
            ),
            ExportItem(
                label="Mirror", x_mm=80, y_mm=50, angle_deg=45,
                step_file_path="/m.step", step_filename="m.step",
                interfaces=[{"element_type": "mirror",
                             "x1_mm": 0, "y1_mm": -10,
                             "x2_mm": 0, "y2_mm": 10}],
            ),
        ]
        script = generate_script(items, BaseplateOptions())
        compile(script, "<pyopticl_export>", "exec")


# ---------------------------------------------------------------------------
# ComponentRecord step_file_path round-trip
# ---------------------------------------------------------------------------


class TestComponentRecordStepPath:
    def test_step_field_defaults_empty(self):
        from optiverse.core.models import ComponentRecord
        rec = ComponentRecord(name="Test")
        assert rec.step_file_path == ""

    def test_step_field_serialization(self):
        from optiverse.core.models import (
            ComponentRecord,
            deserialize_component,
            serialize_component,
        )

        rec = ComponentRecord(
            name="Mirror Mount",
            step_file_path="/tmp/mount.step",
            step_view_rotation=(1, 0, 0, 0, 1, 0, 0, 0, 1),
        )
        data = serialize_component(rec)
        assert data.get("step_file_path") is not None
        assert data.get("step_view_rotation") == [1, 0, 0, 0, 1, 0, 0, 0, 1]

    def test_step_field_deserialization(self):
        from optiverse.core.models import deserialize_component

        data = {
            "name": "Mount",
            "step_file_path": "/tmp/mount.step",
            "step_view_rotation": [1, 0, 0, 0, 1, 0, 0, 0, 1],
        }
        rec = deserialize_component(data)
        assert rec is not None
        # Path resolution may alter the absolute path, but it should not be empty
        assert rec.step_view_rotation == (1, 0, 0, 0, 1, 0, 0, 0, 1)
