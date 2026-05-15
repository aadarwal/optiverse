import numpy as np

from optiverse.agentic.benchmarks import get_benchmark
from optiverse.agentic.catalog import load_builtin_catalog
from optiverse.agentic.scene_writer import build_scene_data, deterministic_uuid
from optiverse.agentic.schema import demo_goal_spec


def test_deterministic_uuid_is_stable():
    assert deterministic_uuid("goal", "item") == deterministic_uuid("goal", "item")
    assert deterministic_uuid("goal", "item") != deterministic_uuid("goal", "other")


def test_build_scene_data_matches_gui_contract_and_is_deterministic():
    catalog = load_builtin_catalog()
    goal = demo_goal_spec()

    scene1 = build_scene_data(catalog, goal)
    scene2 = build_scene_data(catalog, goal)

    assert scene1 == scene2
    assert scene1["version"] == "2.0"
    assert [item["_type"] for item in scene1["items"]] == ["source", "component", "component"]
    assert scene1["items"][1]["item_uuid"] == deterministic_uuid(goal.goal_id, "HWP1")
    assert scene1["items"][2]["interfaces"][0]["is_polarizing"] is True


def test_build_scene_data_places_gui_origin_at_first_interface_midpoint():
    catalog = load_builtin_catalog()
    goal = get_benchmark("two_mirror_steering").goal

    scene = build_scene_data(catalog, goal)
    mirror_items = scene["items"][1:]

    assert np.allclose(
        [(item["x_mm"], item["y_mm"]) for item in mirror_items],
        [(50.0, 0.0), (50.0, 100.0)],
    )
