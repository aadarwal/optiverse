from optiverse.agentic.catalog import load_builtin_catalog
from optiverse.agentic.compiler import compile_elements
from optiverse.agentic.schema import TargetSpec, demo_goal_spec
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

    score = score_paths(paths, goal.targets)

    assert score["passed"] is True
    assert score["target_scores"]["D1_transmitted_H"]["hit"] is True
    assert score["target_scores"]["D1_transmitted_H"]["power_fraction"] == 0.4999999999999999
    assert score["target_scores"]["D1_transmitted_H"]["polarization_overlap"] == 1.0
    assert score["target_scores"]["D2_reflected_V"]["hit"] is True
    assert score["target_scores"]["D2_reflected_V"]["power_fraction"] == 0.5000000000000001
    assert score["target_scores"]["D2_reflected_V"]["polarization_overlap"] == 1.0


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
