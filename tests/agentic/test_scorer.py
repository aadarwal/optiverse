from optiverse.agentic.catalog import load_builtin_catalog
from optiverse.agentic.compiler import compile_elements
from optiverse.agentic.schema import ConstraintSpec, SourceSpec, TargetSpec, demo_goal_spec
from optiverse.agentic.scorer import score_paths
from optiverse.raytracing.engine import trace_rays_polymorphic


def _demo_paths():
    catalog = load_builtin_catalog()
    goal = demo_goal_spec()
    elements = compile_elements(catalog, goal.placements)
    paths = trace_rays_polymorphic(elements, [goal.source.to_source_params()], parallel=False)
    return goal, paths


def test_score_paths_reproduces_demo_result():
    goal, paths = _demo_paths()

    score = score_paths(paths, goal.targets, goal.constraints)

    assert score["passed"] is True
    assert score["target_scores"]["D1_transmitted_H"]["hit"] is True
    assert score["target_scores"]["D1_transmitted_H"]["power_fraction"] == 0.4999999999999999
    assert score["target_scores"]["D1_transmitted_H"]["polarization_overlap"] == 1.0
    assert score["target_scores"]["D2_reflected_V"]["hit"] is True
    assert score["target_scores"]["D2_reflected_V"]["power_fraction"] == 0.5000000000000001
    assert score["target_scores"]["D2_reflected_V"]["polarization_overlap"] == 1.0
    assert score["constraint_scores"][0]["kind"] == "branch_count"
    assert all(item["passed"] for item in score["constraint_scores"])
    assert score["ray_paths"][0]["path_element_ids"] == ["HWP1:iface0", "PBS1:iface0"]


def test_score_paths_fails_near_miss_target():
    _goal, paths = _demo_paths()
    bad_target = TargetSpec(
        name="miss",
        x_mm=300,
        y_mm=20,
        radius_mm=2,
        polarization="horizontal",
        expected_power_fraction=0.5,
    )

    score = score_paths(paths, [bad_target])

    assert score["passed"] is False
    assert score["target_scores"]["miss"]["hit"] is False


def test_path_contains_constraint_fails_for_missing_element():
    goal, paths = _demo_paths()
    constraint = ConstraintSpec(
        kind="path_contains_elements",
        params={
            "target": "D1_transmitted_H",
            "elements": ["HWP1:iface0", "missing:iface0"],
        },
    )

    score = score_paths(paths, goal.targets, [constraint])

    assert score["passed"] is False
    assert score["constraint_scores"][0]["passed"] is False
    assert score["constraint_scores"][0]["matched_paths"] == 0


def test_demo_constraint_kinds_pass_for_expected_values():
    goal, paths = _demo_paths()
    constraints = [
        ConstraintSpec(kind="target_hit", params={"target": "D1_transmitted_H"}),
        ConstraintSpec(
            kind="power_at_target",
            params={"target": "D1_transmitted_H", "expected_power_fraction": 0.5},
        ),
        ConstraintSpec(
            kind="polarization_at_target",
            params={"target": "D1_transmitted_H", "polarization": "horizontal"},
        ),
        ConstraintSpec(
            kind="path_avoids_elements",
            params={"target": "D1_transmitted_H", "elements": ["missing:iface0"]},
        ),
        ConstraintSpec(
            kind="path_length",
            params={"target": "D1_transmitted_H", "min_mm": 499, "max_mm": 501},
        ),
    ]

    score = score_paths(paths, goal.targets, constraints)

    assert score["passed"] is True
    assert [item["passed"] for item in score["constraint_scores"]] == [True] * 5


def test_multi_ray_spot_constraints_measure_centroid_and_rms():
    source = SourceSpec(
        x_mm=0,
        y_mm=0,
        size_mm=10,
        n_rays=3,
        ray_length_mm=100,
        spread_deg=0,
    )
    paths = trace_rays_polymorphic([], [source.to_source_params()], parallel=False)
    constraints = [
        ConstraintSpec(
            kind="spot_centroid_at_plane",
            params={"axis": "x", "value_mm": 100, "expected_x_mm": 100, "expected_y_mm": 0},
        ),
        ConstraintSpec(
            kind="spot_rms_radius_at_plane",
            params={"axis": "x", "value_mm": 100, "expected_mm": 4.08248290463863},
        ),
    ]

    score = score_paths(paths, [], constraints)

    assert score["passed"] is True
    assert score["constraint_scores"][0]["sample_count"] == 3
    assert score["constraint_scores"][0]["centroid_mm"] == [100.0, 0.0]
    assert score["constraint_scores"][1]["sample_count"] == 3
    assert score["constraint_scores"][1]["spot_rms_radius_mm"] == 4.08248290463863
