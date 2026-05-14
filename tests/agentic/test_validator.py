from dataclasses import replace

from optiverse.agentic.catalog import load_builtin_catalog
from optiverse.agentic.schema import (
    ConstraintSpec,
    Placement,
    SourceSpec,
    TargetSpec,
    demo_goal_spec,
)
from optiverse.agentic.validator import validate_goal


def test_validate_demo_goal_passes():
    catalog = load_builtin_catalog()
    goal = demo_goal_spec()

    result = validate_goal(goal, catalog)

    assert result.passed is True
    assert result.errors == []


def test_validate_unknown_catalog_id_fails_before_raytracing():
    catalog = load_builtin_catalog()
    goal = replace(
        demo_goal_spec(),
        placements=[Placement(label="BAD", catalog_id="not_real", x_mm=0, y_mm=0)],
    )

    result = validate_goal(goal, catalog)

    assert result.passed is False
    assert result.errors[0].code == "unknown_catalog_id"


def test_validate_bad_interface_override_index_and_field_fail():
    catalog = load_builtin_catalog()
    goal = replace(
        demo_goal_spec(),
        placements=[
            Placement(
                label="HWP1",
                catalog_id="waveplate_hwp",
                x_mm=60,
                y_mm=0,
                interface_overrides={
                    0: {"not_a_waveplate_property": 1.0},
                    9: {"fast_axis_deg": 22.5},
                },
            )
        ],
    )

    result = validate_goal(goal, catalog)
    codes = {issue.code for issue in result.errors}

    assert "invalid_override_index" in codes
    assert "invalid_override_field" in codes


def test_validate_overlap_and_table_bounds_fail():
    catalog = load_builtin_catalog()
    goal = replace(
        demo_goal_spec(),
        placements=[
            Placement(label="L1", catalog_id="lens_standard_1in", x_mm=0, y_mm=0),
            Placement(label="L2", catalog_id="lens_standard_1in", x_mm=5, y_mm=0),
        ],
    )

    result = validate_goal(goal, catalog, table_rect=(-10, -10, 10, 10))
    codes = {issue.code for issue in result.errors}

    assert "footprint_overlap" in codes
    assert "placement_out_of_bounds" in codes


def test_validate_source_target_and_constraint_fields():
    catalog = load_builtin_catalog()
    goal = replace(
        demo_goal_spec(),
        source=SourceSpec(n_rays=0, wavelength_nm=0),
        targets=[
            TargetSpec(
                name="bad",
                x_mm=0,
                y_mm=0,
                radius_mm=0,
                polarization="horizontal",
                expected_power_fraction=1.5,
            )
        ],
        constraints=[
            ConstraintSpec(kind="target_hit", params={"target": "missing"}),
            ConstraintSpec(kind="path_contains_elements", params={"elements": "HWP1:iface0"}),
        ],
    )

    result = validate_goal(goal, catalog)
    codes = {issue.code for issue in result.errors}

    assert "invalid_source_field" in codes
    assert "invalid_target_field" in codes
    assert "unknown_constraint_target" in codes
    assert "invalid_constraint_elements" in codes
