import json

from optiverse.agentic.benchmarks import get_benchmark
from optiverse.agentic.experiments import evaluate_planner_output, make_prompt


def test_make_prompt_includes_goal_and_catalog():
    prompt = make_prompt("hwp_pbs_splitter", "direct-placement")

    assert "hwp_pbs_splitter" in prompt
    assert "waveplate_hwp" in prompt
    assert '"placements"' in prompt


def test_evaluate_direct_placement_saved_output_passes(tmp_path):
    spec = get_benchmark("hwp_pbs_splitter")
    planner_output = {
        "placements": [placement.to_dict() for placement in spec.goal.placements],
    }
    planner_output_path = tmp_path / "model_output.json"
    planner_output_path.write_text(json.dumps(planner_output), encoding="utf-8")

    report = evaluate_planner_output(
        benchmark_id="hwp_pbs_splitter",
        mode="direct-placement",
        planner_output_path=planner_output_path,
        output_dir=tmp_path / "out",
    )

    assert report["passed"] is True
    assert report["failure_stage"] is None
    assert (tmp_path / "out" / "hwp_pbs_splitter" / "direct-placement" / "scene.json").exists()


def test_evaluate_direct_placement_schema_failure(tmp_path):
    planner_output_path = tmp_path / "model_output.json"
    planner_output_path.write_text(json.dumps({"components": []}), encoding="utf-8")

    report = evaluate_planner_output(
        benchmark_id="hwp_pbs_splitter",
        mode="direct-placement",
        planner_output_path=planner_output_path,
        output_dir=tmp_path / "out",
    )

    assert report["passed"] is False
    assert report["failure_stage"] == "schema"


def test_evaluate_topology_output_archives_without_tracing(tmp_path):
    planner_output_path = tmp_path / "model_output.json"
    planner_output_path.write_text(
        json.dumps({"topology": "source -> HWP -> PBS", "components": []}),
        encoding="utf-8",
    )

    report = evaluate_planner_output(
        benchmark_id="hwp_pbs_splitter",
        mode="topology",
        planner_output_path=planner_output_path,
        output_dir=tmp_path / "out",
    )

    assert report["passed"] is True
    assert report["archived_only"] is True
    assert (tmp_path / "out" / "hwp_pbs_splitter" / "topology" / "model_output.json").exists()
