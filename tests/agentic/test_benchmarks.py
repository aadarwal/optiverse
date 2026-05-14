import json

from optiverse.agentic.benchmarks import (
    benchmark_specs,
    export_benchmark_fixtures,
    run_all_benchmarks,
    run_benchmark,
)
from optiverse.agentic.cli import main


def test_benchmark_registry_contains_required_cases():
    specs = benchmark_specs()

    assert set(specs) == {
        "hwp_pbs_splitter",
        "two_mirror_steering",
        "single_lens_focus",
        "four_f_telescope",
        "mach_zehnder_skeleton",
    }
    assert specs["single_lens_focus"].goal.source.n_rays == 7
    assert specs["four_f_telescope"].expected_limitations


def test_first_three_benchmarks_pass(tmp_path):
    for benchmark_id in ["hwp_pbs_splitter", "two_mirror_steering", "single_lens_focus"]:
        report = run_benchmark(benchmark_id, output_dir=tmp_path)

        assert report["validation"]["passed"] is True
        assert report["score"]["passed"] is True
        assert (tmp_path / benchmark_id / "goal.json").exists()
        assert (tmp_path / benchmark_id / "explicit_placements.json").exists()
        assert (tmp_path / benchmark_id / "scene.json").exists()
        assert (tmp_path / benchmark_id / "report.json").exists()


def test_run_all_benchmarks_writes_summary(tmp_path):
    summary = run_all_benchmarks(output_dir=tmp_path)

    assert summary["passed"] is True
    assert len(summary["benchmarks"]) == 5
    assert (tmp_path / "summary.json").exists()
    mz = next(
        item for item in summary["benchmarks"] if item["benchmark_id"] == "mach_zehnder_skeleton"
    )
    assert mz["expected_limitations"]


def test_export_benchmark_fixtures_writes_goal_and_placements(tmp_path):
    summary = export_benchmark_fixtures(output_dir=tmp_path)

    assert len(summary["benchmarks"]) == 5
    first = summary["benchmarks"][0]
    assert (tmp_path / first["benchmark_id"] / "goal.json").exists()
    placements = json.loads(
        (tmp_path / first["benchmark_id"] / "explicit_placements.json").read_text()
    )
    assert placements["placements"]


def test_run_benchmark_cli(tmp_path):
    exit_code = main(
        [
            "run-benchmark",
            "hwp_pbs_splitter",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "hwp_pbs_splitter" / "report.json").exists()
