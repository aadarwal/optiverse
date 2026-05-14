"""Prompt generation and saved planner-output evaluation for benchmark experiments."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from optiverse.raytracing.engine import trace_rays_polymorphic

from .benchmarks import BenchmarkSpec, get_benchmark
from .catalog import catalog_summary, load_builtin_catalog
from .compiler import compile_elements
from .scene_writer import build_scene_data, write_json
from .schema import GoalSpec, Placement
from .scorer import score_paths
from .validator import validate_goal

DIRECT_PLACEMENT_MODE = "direct-placement"
TOPOLOGY_MODE = "topology"
SUPPORTED_MODES = {DIRECT_PLACEMENT_MODE, TOPOLOGY_MODE}


def _planner_goal_payload(spec: BenchmarkSpec) -> dict[str, Any]:
    goal = spec.goal.to_dict()
    goal.pop("placements", None)
    return {
        "benchmark_id": spec.benchmark_id,
        "goal": goal,
        "expected_limitations": spec.expected_limitations,
    }


def make_prompt(benchmark_id: str, mode: str) -> str:
    """Generate an LLM prompt for one benchmark and planner mode."""
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported planner mode: {mode}")

    catalog = load_builtin_catalog()
    spec = get_benchmark(benchmark_id, catalog)
    payload = _planner_goal_payload(spec)
    catalog_payload = catalog_summary(catalog)

    if mode == DIRECT_PLACEMENT_MODE:
        task = (
            "Emit explicit Optiverse component placements for the benchmark. "
            "Use only catalog_id values from the catalog. Return JSON only with this shape:\n"
            "{\n"
            '  "placements": [\n'
            "    {\n"
            '      "label": "HWP1",\n'
            '      "catalog_id": "waveplate_hwp",\n'
            '      "x_mm": 60.0,\n'
            '      "y_mm": 0.0,\n'
            '      "angle_deg": 0.0,\n'
            '      "interface_overrides": {"0": {"fast_axis_deg": 22.5}}\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Do not include prose or markdown fences."
        )
    else:
        task = (
            "Emit qualitative topology and intent only. Do not emit x/y coordinates. "
            "Return JSON only with keys such as topology, components, parameters, "
            "ports, and constraints. Include artifact-level parameters like HWP "
            "fast-axis angle or lens focal length when they are part of the intent."
        )

    return "\n\n".join(
        [
            "You are planning a headless Optiverse optical layout benchmark.",
            task,
            "Benchmark goal JSON:",
            json.dumps(payload, indent=2, sort_keys=True),
            "Available component catalog summary:",
            json.dumps(catalog_payload, indent=2, sort_keys=True),
        ]
    )


def _load_json_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"Could not parse JSON: {exc}"
    if not isinstance(data, dict):
        return None, "Planner output must be a JSON object"
    return data, None


def _placements_from_output(data: dict[str, Any]) -> tuple[list[Placement], list[str]]:
    errors = []
    raw_placements = data.get("placements", data.get("explicit_placements"))
    if not isinstance(raw_placements, list):
        return [], ["Planner output must contain a placements list"]

    placements = []
    for index, raw in enumerate(raw_placements):
        if not isinstance(raw, dict):
            errors.append(f"placements[{index}] must be an object")
            continue
        try:
            placements.append(Placement.from_dict(raw))
        except Exception as exc:
            errors.append(f"placements[{index}] is invalid: {exc}")
    return placements, errors


def _direct_goal_from_output(
    spec: BenchmarkSpec, data: dict[str, Any]
) -> tuple[GoalSpec | None, list[str]]:
    placements, errors = _placements_from_output(data)
    if errors:
        return None, errors
    return replace(spec.goal, placements=placements), []


def _report_failure(
    *,
    benchmark_id: str,
    mode: str,
    failure_stage: str,
    errors: list[str],
    planner_output: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "benchmark_id": benchmark_id,
        "mode": mode,
        "passed": False,
        "failure_stage": failure_stage,
        "errors": errors,
        "planner_output": planner_output,
    }


def _unsupported_checks(score: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in score.get("constraint_scores", [])
        if isinstance(item, dict) and item.get("unsupported")
    ]


def evaluate_planner_output(
    *,
    benchmark_id: str,
    mode: str,
    planner_output_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Evaluate or archive one saved planner output."""
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported planner mode: {mode}")

    catalog = load_builtin_catalog()
    spec = get_benchmark(benchmark_id, catalog)
    data, load_error = _load_json_file(planner_output_path)
    experiment_dir = output_dir / benchmark_id / mode
    prompt_path = experiment_dir / "prompt.txt"
    output_archive_path = experiment_dir / "model_output.json"
    report_path = experiment_dir / "report.json"

    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(make_prompt(benchmark_id, mode), encoding="utf-8")

    if load_error is not None:
        report = _report_failure(
            benchmark_id=benchmark_id,
            mode=mode,
            failure_stage="schema",
            errors=[load_error],
            planner_output=None,
        )
        write_json(report_path, report)
        return report

    assert data is not None
    write_json(output_archive_path, data)

    if mode == TOPOLOGY_MODE:
        warnings = []
        if not any(key in data for key in ("topology", "components", "sequence", "graph")):
            warnings.append("No topology-like key found; archived for manual inspection only.")
        report = {
            "benchmark_id": benchmark_id,
            "mode": mode,
            "passed": True,
            "failure_stage": None,
            "archived_only": True,
            "warnings": warnings,
            "planner_output": data,
            "output_files": {
                "prompt": str(prompt_path),
                "model_output": str(output_archive_path),
                "report": str(report_path),
            },
        }
        write_json(report_path, report)
        return report

    goal, schema_errors = _direct_goal_from_output(spec, data)
    if goal is None:
        report = _report_failure(
            benchmark_id=benchmark_id,
            mode=mode,
            failure_stage="schema",
            errors=schema_errors,
            planner_output=data,
        )
        write_json(report_path, report)
        return report

    validation = validate_goal(goal, catalog)
    if not validation.passed:
        report = {
            "benchmark_id": benchmark_id,
            "mode": mode,
            "passed": False,
            "failure_stage": "validation",
            "validation": validation.to_dict(),
            "planner_output": data,
        }
        write_json(report_path, report)
        return report

    try:
        elements = compile_elements(catalog, goal.placements)
        paths = trace_rays_polymorphic(
            elements,
            [goal.source.to_source_params()],
            parallel=False,
            min_intensity=0.0,
        )
        score = score_paths(paths, goal.targets, goal.constraints)
    except Exception as exc:
        report = _report_failure(
            benchmark_id=benchmark_id,
            mode=mode,
            failure_stage="trace",
            errors=[str(exc)],
            planner_output=data,
        )
        write_json(report_path, report)
        return report

    scene_path = experiment_dir / "scene.json"
    write_json(scene_path, build_scene_data(catalog, goal))

    passed = bool(score["passed"])
    report = {
        "benchmark_id": benchmark_id,
        "mode": mode,
        "passed": passed,
        "failure_stage": None if passed else "score",
        "validation": validation.to_dict(),
        "score": score,
        "unsupported_checks": _unsupported_checks(score),
        "planner_output": data,
        "output_files": {
            "prompt": str(prompt_path),
            "model_output": str(output_archive_path),
            "scene": str(scene_path),
            "report": str(report_path),
        },
    }
    write_json(report_path, report)
    return report
