"""Command-line entry points for the headless agentic layout harness."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from optiverse.raytracing.engine import trace_rays_polymorphic
from optiverse.raytracing.ray import RayPath

from .benchmarks import export_benchmark_fixtures, run_all_benchmarks, run_benchmark
from .catalog import Catalog, catalog_summary, load_builtin_catalog
from .compiler import compile_elements
from .experiments import evaluate_planner_output, make_prompt
from .goal_parser import PARSE_GOAL_PROMPT_VERSION, parse_goal_with_provider
from .layout_compiler import goal_from_planner_data
from .llm_client import LLMProviderError, call_provider
from .render import render_goal_png
from .scene_writer import build_scene_data, write_json
from .schema import GoalSpec, demo_goal_spec
from .scorer import score_paths, serialize_ray_path
from .validator import ValidationResult, validate_goal

AGENTIC_METADATA_KEY = "_agentic"
AGENTIC_SCHEMA_VERSION = 1


def run_demo(output_dir: Path) -> dict[str, Any]:
    """Run the HWP/PBS splitter demo and write scene/report/catalog outputs."""
    catalog = load_builtin_catalog()
    goal = demo_goal_spec()
    validation = validate_goal(goal, catalog)
    if not validation.passed:
        raise ValueError(f"Invalid demo goal: {validation.to_dict()}")

    elements = compile_elements(catalog, goal.placements)
    paths = trace_rays_polymorphic(elements, [goal.source.to_source_params()], parallel=False)
    score = score_paths(paths, goal.targets, goal.constraints)

    scene_data = build_scene_data(catalog, goal)
    report = {
        "goal": goal.description,
        "goal_id": goal.goal_id,
        "topology": goal.topology,
        "placements": [placement.to_dict() for placement in goal.placements],
        "targets": [target.to_dict() for target in goal.targets],
        "constraints": [constraint.to_dict() for constraint in goal.constraints],
        "validation": validation.to_dict(),
        "score": score,
    }

    scene_path = output_dir / "agentic_hwp_pbs.scene.json"
    report_path = output_dir / "agentic_hwp_pbs.report.json"
    catalog_path = output_dir / "agentic_hwp_pbs.catalog.json"

    write_json(scene_path, scene_data)
    write_json(report_path, report)
    write_json(catalog_path, catalog_summary(catalog))

    return {
        "goal": goal,
        "paths": paths,
        "score": score,
        "scene_path": scene_path,
        "report_path": report_path,
        "catalog_path": catalog_path,
    }


def print_demo_result(result: dict[str, Any]) -> None:
    """Print a compact human-readable demo report."""
    goal = result["goal"]
    score = result["score"]
    print(f"goal: {goal.description}")
    print(f"paths: {len(result['paths'])}")
    for target_name, target_score in score["target_scores"].items():
        print(
            f"{target_name}: hit={target_score['hit']} "
            f"distance={target_score['closest_distance_mm']:.6g} mm "
            f"power={target_score['power_fraction']:.6g} "
            f"pol_overlap={target_score['polarization_overlap']:.6g}"
        )
    print(f"passed: {score['passed']}")
    print(f"scene: {result['scene_path']}")
    print(f"report: {result['report_path']}")
    print(f"catalog: {result['catalog_path']}")


def demo_main(argv: Sequence[str] | None = None) -> int:
    """Compatibility entry point for the original example script."""
    parser = argparse.ArgumentParser(description="Run the HWP/PBS headless layout demo.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("examples/output"),
        help="Directory for generated scene/report files.",
    )
    args = parser.parse_args(argv)
    result = run_demo(args.output_dir)
    print_demo_result(result)
    return 0 if result["score"]["passed"] else 1


def _read_json_argument(value: str) -> dict[str, Any]:
    if value == "-":
        raw = sys.stdin.read()
        source = "stdin"
    else:
        path = Path(value)
        raw = path.read_text(encoding="utf-8")
        source = str(path)

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{source} must contain a JSON object")
    return data


def _emit_json(data: Any, output: Path | None = None) -> None:
    text = json.dumps(data, indent=2) + "\n"
    if output is None:
        sys.stdout.write(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _goal_from_data(catalog: Catalog, data: dict[str, Any]) -> GoalSpec:
    metadata = data.get(AGENTIC_METADATA_KEY)
    if isinstance(metadata, dict) and isinstance(metadata.get("goal"), dict):
        return goal_from_planner_data(catalog, metadata["goal"])
    if isinstance(data.get("goal"), dict):
        return goal_from_planner_data(catalog, data["goal"])
    if "goal_id" in data and "source" in data:
        return goal_from_planner_data(catalog, data)
    raise ValueError(
        "input must be a GoalSpec JSON object, a benchmark wrapper with a "
        "'goal' object, or a scene JSON object with _agentic.goal"
    )


def _metadata_for(document: dict[str, Any]) -> dict[str, Any]:
    metadata = document.get(AGENTIC_METADATA_KEY)
    if not isinstance(metadata, dict):
        metadata = {}
        document[AGENTIC_METADATA_KEY] = metadata
    metadata.setdefault("schema_version", AGENTIC_SCHEMA_VERSION)
    return metadata


def _build_agentic_scene(catalog: Catalog, goal: GoalSpec) -> dict[str, Any]:
    scene_data = build_scene_data(catalog, goal)
    _metadata_for(scene_data)["goal"] = goal.to_dict()
    return scene_data


def _is_scene_document(data: dict[str, Any]) -> bool:
    return data.get("version") == "2.0" and isinstance(data.get("items"), list)


def _scene_document_from_data(catalog: Catalog, data: dict[str, Any]) -> dict[str, Any]:
    if _is_scene_document(data):
        document = copy.deepcopy(data)
        metadata = _metadata_for(document)
        if "goal" not in metadata:
            metadata["goal"] = _goal_from_data(catalog, data).to_dict()
        return document
    return _build_agentic_scene(catalog, _goal_from_data(catalog, data))


def _trace_goal(catalog: Catalog, goal: GoalSpec) -> tuple[ValidationResult, list[RayPath]]:
    validation = validate_goal(goal, catalog)
    if not validation.passed:
        return validation, []
    elements = compile_elements(catalog, goal.placements)
    paths = trace_rays_polymorphic(
        elements,
        [goal.source.to_source_params()],
        parallel=False,
        min_intensity=0.0,
    )
    return validation, paths


def _attach_validation(document: dict[str, Any], validation: ValidationResult) -> None:
    _metadata_for(document)["validation"] = validation.to_dict()


def _attach_trace(document: dict[str, Any], paths: list[RayPath]) -> None:
    _metadata_for(document)["trace"] = {
        "path_count": len(paths),
        "ray_paths": [serialize_ray_path(path) for path in paths],
    }


def _cmd_compile(args: argparse.Namespace) -> int:
    catalog = load_builtin_catalog()
    document = _scene_document_from_data(catalog, _read_json_argument(args.input))
    _emit_json(document, args.output)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    catalog = load_builtin_catalog()
    document = _scene_document_from_data(catalog, _read_json_argument(args.input))
    validation = validate_goal(_goal_from_data(catalog, document), catalog)
    _attach_validation(document, validation)
    _emit_json(document, args.output)
    return 0 if validation.passed else 1


def _cmd_trace(args: argparse.Namespace) -> int:
    catalog = load_builtin_catalog()
    document = _scene_document_from_data(catalog, _read_json_argument(args.input))
    validation, paths = _trace_goal(catalog, _goal_from_data(catalog, document))
    _attach_validation(document, validation)
    _attach_trace(document, paths)
    _emit_json(document, args.output)
    return 0 if validation.passed else 1


def _cmd_score(args: argparse.Namespace) -> int:
    catalog = load_builtin_catalog()
    scene_data = _read_json_argument(args.input)
    document = _scene_document_from_data(catalog, scene_data)
    goal = (
        _goal_from_data(catalog, _read_json_argument(args.goal))
        if args.goal
        else _goal_from_data(catalog, document)
    )
    validation, paths = _trace_goal(catalog, goal)
    score = score_paths(paths, goal.targets, goal.constraints)
    report = {
        "goal_id": goal.goal_id,
        "validation": validation.to_dict(),
        "path_count": len(paths),
        "score": score,
    }
    _emit_json(report, args.output)
    return 0 if validation.passed and score["passed"] else 1


def _render_output_path(input_value: str, output: Path | None) -> Path:
    if output is not None:
        return output
    if input_value != "-":
        return Path(input_value).with_suffix(".png")
    return Path("agentic_render.png")


def _cmd_render(args: argparse.Namespace) -> int:
    catalog = load_builtin_catalog()
    document = _scene_document_from_data(catalog, _read_json_argument(args.input))
    goal = _goal_from_data(catalog, document)
    metadata = _metadata_for(document)
    trace = metadata.get("trace")
    if isinstance(trace, dict) and isinstance(trace.get("ray_paths"), list):
        ray_paths = trace["ray_paths"]
    else:
        validation, paths = _trace_goal(catalog, goal)
        _attach_validation(document, validation)
        _attach_trace(document, paths)
        ray_paths = _metadata_for(document)["trace"]["ray_paths"]

    output_path = _render_output_path(args.input, args.output)
    render_goal_png(goal, ray_paths, output_path)
    _emit_json(
        {
            "rendered": str(output_path),
            "goal_id": goal.goal_id,
            "path_count": len(ray_paths),
        }
    )
    return 0


def _launch_gui(scene_path: Path) -> dict[str, Any]:
    if not scene_path.exists():
        raise ValueError(f"scene file does not exist: {scene_path}")
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "optiverse.app.main", str(scene_path.resolve())]
    )
    return {"opened": str(scene_path), "pid": process.pid}


def _cmd_open(args: argparse.Namespace) -> int:
    _emit_json(_launch_gui(Path(args.input)))
    return 0


def _cmd_catalog(args: argparse.Namespace) -> int:
    _emit_json(catalog_summary(load_builtin_catalog()), args.output)
    return 0


def _cmd_parse_goal(args: argparse.Namespace) -> int:
    catalog = load_builtin_catalog()
    try:
        goal, _response = parse_goal_with_provider(
            args.request,
            catalog,
            provider=args.provider,
            model=args.model,
            max_tokens=args.max_tokens,
            prompt_version=args.prompt_version,
        )
    except LLMProviderError as exc:
        print(f"provider_error: {exc}", file=sys.stderr)
        return 1
    _emit_json(goal.to_dict(), args.output)
    return 0


def _failure_feedback(validation: dict[str, Any], score: dict[str, Any]) -> str:
    failed_constraints = [
        item.get("name", item.get("kind"))
        for item in score.get("constraint_scores", [])
        if not item.get("passed", False)
    ]
    missed_targets = [
        name
        for name, target_score in score.get("target_scores", {}).items()
        if not target_score.get("hit", False)
    ]
    return json.dumps(
        {
            "validation_passed": validation.get("passed", False),
            "missed_targets": missed_targets,
            "failed_constraints": failed_constraints,
        },
        sort_keys=True,
    )


def _cmd_design(args: argparse.Namespace) -> int:
    catalog = load_builtin_catalog()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    base_request = args.request
    request = base_request
    attempts = []
    final_report: dict[str, Any] | None = None

    for round_index in range(1, args.max_rounds + 1):
        try:
            goal, _response = parse_goal_with_provider(
                request,
                catalog,
                provider=args.provider,
                model=args.model,
                max_tokens=args.max_tokens,
                prompt_version=args.prompt_version,
            )
        except LLMProviderError as exc:
            print(f"provider_error: {exc}", file=sys.stderr)
            return 1

        document = _build_agentic_scene(catalog, goal)
        validation, paths = _trace_goal(catalog, goal)
        _attach_validation(document, validation)
        _attach_trace(document, paths)
        score = score_paths(paths, goal.targets, goal.constraints)
        _metadata_for(document)["score"] = score
        passed = validation.passed and bool(score["passed"])
        attempts.append(
            {
                "round": round_index,
                "goal_id": goal.goal_id,
                "validation_passed": validation.passed,
                "score_passed": bool(score["passed"]),
                "passed": passed,
            }
        )

        if passed:
            scene_path = output_dir / "design.scene.json"
            render_path = output_dir / "design.png"
            report_path = output_dir / "design.report.json"
            render_goal_png(goal, score["ray_paths"], render_path)
            write_json(scene_path, document)
            opened = None if args.no_open else _launch_gui(scene_path)
            final_report = {
                "passed": True,
                "attempts": attempts,
                "goal": goal.to_dict(),
                "scene": str(scene_path),
                "render": str(render_path),
                "opened": opened,
                "score": score,
            }
            write_json(report_path, final_report)
            _emit_json(final_report, args.output)
            return 0

        request = (
            f"{base_request}\n\nPrevious Optiverse attempt failed. "
            f"Use this machine-readable feedback to revise the GoalSpec: "
            f"{_failure_feedback(validation.to_dict(), score)}"
        )

    final_report = {
        "passed": False,
        "attempts": attempts,
        "error": f"no passing design after {args.max_rounds} rounds",
    }
    write_json(output_dir / "design.report.json", final_report)
    _emit_json(final_report, args.output)
    return 1


def _cmd_demo(args: argparse.Namespace) -> int:
    result = run_demo(args.output_dir)
    print_demo_result(result)
    return 0 if result["score"]["passed"] else 1


def _cmd_run_benchmark(args: argparse.Namespace) -> int:
    report = run_benchmark(args.benchmark, output_dir=args.output_dir)
    print(f"benchmark: {report['benchmark_id']}")
    print(f"passed: {report['score']['passed']}")
    print(f"report: {report['output_files']['report']}")
    return 0 if report["score"]["passed"] and report["validation"]["passed"] else 1


def _cmd_run_all_benchmarks(args: argparse.Namespace) -> int:
    summary = run_all_benchmarks(output_dir=args.output_dir)
    print(f"benchmarks: {len(summary['benchmarks'])}")
    print(f"passed: {summary['passed']}")
    print(f"summary: {args.output_dir / 'summary.json'}")
    return 0 if summary["passed"] else 1


def _cmd_export_benchmark_fixtures(args: argparse.Namespace) -> int:
    summary = export_benchmark_fixtures(output_dir=args.output_dir)
    print(f"benchmarks: {len(summary['benchmarks'])}")
    print(f"fixtures: {args.output_dir}")
    return 0


def _cmd_make_prompt(args: argparse.Namespace) -> int:
    print(make_prompt(args.benchmark, args.mode))
    return 0


def _cmd_evaluate_planner_output(args: argparse.Namespace) -> int:
    report = evaluate_planner_output(
        benchmark_id=args.benchmark,
        mode=args.mode,
        planner_output_path=args.planner_output,
        output_dir=args.output_dir,
    )
    print(f"benchmark: {report['benchmark_id']}")
    print(f"mode: {report['mode']}")
    print(f"passed: {report['passed']}")
    print(f"failure_stage: {report.get('failure_stage')}")
    return 0 if report["passed"] else 1


def _cmd_run_llm_benchmark(args: argparse.Namespace) -> int:
    prompt = make_prompt(args.benchmark, args.mode)
    input_dir = Path("examples/agentic_experiments") / args.benchmark / args.mode
    input_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = input_dir / "prompt.txt"
    raw_response_path = input_dir / "raw_response.txt"
    model_output_path = input_dir / "model_output.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    try:
        response = call_provider(
            args.provider,
            prompt,
            model=args.model,
            max_tokens=args.max_tokens,
        )
    except LLMProviderError as exc:
        print(f"provider_error: {exc}")
        return 1
    raw_response_path.write_text(response.raw_text, encoding="utf-8")
    write_json(input_dir / "provider_response.json", response.to_dict())
    if response.parsed_json is None:
        print("passed: False")
        print("failure_stage: schema")
        print(f"raw_response: {raw_response_path}")
        return 1
    write_json(model_output_path, response.parsed_json)
    report = evaluate_planner_output(
        benchmark_id=args.benchmark,
        mode=args.mode,
        planner_output_path=model_output_path,
        output_dir=args.output_dir,
    )
    print(f"benchmark: {report['benchmark_id']}")
    print(f"mode: {report['mode']}")
    print(f"passed: {report['passed']}")
    print(f"report: {args.output_dir / args.benchmark / args.mode / 'report.json'}")
    return 0 if report["passed"] else 1


def _add_output_argument(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument("--output", type=Path, default=None, help=help_text)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Headless agentic Optiverse layout tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo_parser = subparsers.add_parser("demo", help="Run the HWP/PBS proof-of-concept.")
    demo_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("examples/output"),
        help="Directory for generated scene/report files.",
    )
    demo_parser.set_defaults(handler=_cmd_demo)

    catalog_parser = subparsers.add_parser(
        "catalog",
        help="Export the built-in catalog summary as JSON.",
        description="Export the built-in catalog summary as JSON to stdout or --output.",
    )
    _add_output_argument(catalog_parser, "Optional path to write the catalog JSON.")
    catalog_parser.set_defaults(handler=_cmd_catalog)

    parse_goal_parser = subparsers.add_parser(
        "parse-goal",
        help="Parse a natural-language experiment request into GoalSpec JSON.",
        description=(
            "Parse natural language into GoalSpec JSON through a provider. The "
            "mock provider is deterministic and requires no network."
        ),
    )
    parse_goal_parser.add_argument("request", help="Natural-language experiment request.")
    parse_goal_parser.add_argument("--provider", default="mock", help="Provider name.")
    parse_goal_parser.add_argument("--model", default=None, help="Provider model name.")
    parse_goal_parser.add_argument(
        "--max-tokens",
        type=int,
        default=4000,
        help="Maximum provider response tokens.",
    )
    parse_goal_parser.add_argument(
        "--prompt-version",
        default=PARSE_GOAL_PROMPT_VERSION,
        help="Versioned prompt template to use.",
    )
    _add_output_argument(parse_goal_parser, "Optional path to write GoalSpec JSON.")
    parse_goal_parser.set_defaults(handler=_cmd_parse_goal)

    design_parser = subparsers.add_parser(
        "design",
        help="Parse, compile, validate, trace, score, render, and optionally open a layout.",
        description=(
            "Run the thin agentic design loop. The command retries failed designs "
            "up to --max-rounds and opens the Optiverse GUI on success unless "
            "--no-open is set."
        ),
    )
    design_parser.add_argument("request", help="Natural-language experiment request.")
    design_parser.add_argument("--provider", default="mock", help="Provider name.")
    design_parser.add_argument("--model", default=None, help="Provider model name.")
    design_parser.add_argument(
        "--max-tokens",
        type=int,
        default=4000,
        help="Maximum provider response tokens.",
    )
    design_parser.add_argument(
        "--prompt-version",
        default=PARSE_GOAL_PROMPT_VERSION,
        help="Versioned prompt template to use.",
    )
    design_parser.add_argument(
        "--max-rounds",
        type=int,
        default=3,
        help="Maximum parse/score refinement rounds.",
    )
    design_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("examples/output/designs"),
        help="Directory for generated scene/render/report files.",
    )
    design_parser.add_argument("--no-open", action="store_true", help="Do not launch the GUI.")
    _add_output_argument(design_parser, "Optional path to write design report JSON.")
    design_parser.set_defaults(handler=_cmd_design)

    compile_parser = subparsers.add_parser(
        "compile",
        help="Compile GoalSpec JSON into GUI-loadable scene JSON.",
        description=(
            "Read GoalSpec JSON, a benchmark wrapper, or '-' from stdin and emit "
            "GUI-loadable scene JSON. The scene carries _agentic metadata so it "
            "can be piped into validate and trace. Placements may use existing "
            "origin x_mm/y_mm fields or planner-friendly interface anchors."
        ),
    )
    compile_parser.add_argument("input", help="Input GoalSpec/benchmark JSON path, or '-'.")
    _add_output_argument(compile_parser, "Optional path to write scene JSON.")
    compile_parser.set_defaults(handler=_cmd_compile)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an agentic scene or goal JSON document.",
        description=(
            "Read scene/goal JSON from a path or '-' and emit the same scene JSON "
            "with _agentic.validation attached."
        ),
    )
    validate_parser.add_argument("input", help="Input scene/goal JSON path, or '-'.")
    _add_output_argument(validate_parser, "Optional path to write validated scene JSON.")
    validate_parser.set_defaults(handler=_cmd_validate)

    trace_parser = subparsers.add_parser(
        "trace",
        help="Raytrace an agentic scene or goal JSON document.",
        description=(
            "Read scene/goal JSON from a path or '-' and emit scene JSON with "
            "_agentic.validation and _agentic.trace attached."
        ),
    )
    trace_parser.add_argument("input", help="Input scene/goal JSON path, or '-'.")
    _add_output_argument(trace_parser, "Optional path to write traced scene JSON.")
    trace_parser.set_defaults(handler=_cmd_trace)

    score_parser = subparsers.add_parser(
        "score",
        help="Score traced or traceable scene JSON against a GoalSpec.",
        description=(
            "Read scene JSON from a path or '-' and emit score JSON. If the scene "
            "does not carry _agentic.goal, pass --goal."
        ),
    )
    score_parser.add_argument("input", help="Input scene JSON path, or '-'.")
    score_parser.add_argument("--goal", help="Optional separate GoalSpec JSON path.")
    _add_output_argument(score_parser, "Optional path to write score JSON.")
    score_parser.set_defaults(handler=_cmd_score)

    render_parser = subparsers.add_parser(
        "render",
        help="Render an agentic scene JSON document to a PNG schematic.",
        description=(
            "Read scene/goal JSON from a path or '-' and render a PNG schematic. "
            "A compact JSON render report is written to stdout."
        ),
    )
    render_parser.add_argument("input", help="Input scene/goal JSON path, or '-'.")
    _add_output_argument(
        render_parser,
        "PNG output path. Defaults beside input or agentic_render.png for stdin.",
    )
    render_parser.set_defaults(handler=_cmd_render)

    open_parser = subparsers.add_parser(
        "open",
        help="Launch the Optiverse GUI on a scene JSON file.",
        description="Launch the Optiverse GUI with the given scene JSON file path.",
    )
    open_parser.add_argument("input", help="Scene JSON file path.")
    open_parser.set_defaults(handler=_cmd_open)

    run_benchmark_parser = subparsers.add_parser(
        "run-benchmark", help="Run one built-in explicit-placement benchmark."
    )
    run_benchmark_parser.add_argument("benchmark", help="Benchmark ID to run.")
    run_benchmark_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("examples/output/benchmarks"),
        help="Directory for generated benchmark outputs.",
    )
    run_benchmark_parser.set_defaults(handler=_cmd_run_benchmark)

    run_all_parser = subparsers.add_parser(
        "run-all-benchmarks", help="Run all built-in explicit-placement benchmarks."
    )
    run_all_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("examples/output/benchmarks"),
        help="Directory for generated benchmark outputs.",
    )
    run_all_parser.set_defaults(handler=_cmd_run_all_benchmarks)

    export_fixtures_parser = subparsers.add_parser(
        "export-benchmark-fixtures", help="Write benchmark goal and placement fixtures."
    )
    export_fixtures_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("examples/agentic_benchmarks"),
        help="Directory for benchmark fixture JSON files.",
    )
    export_fixtures_parser.set_defaults(handler=_cmd_export_benchmark_fixtures)

    make_prompt_parser = subparsers.add_parser(
        "make-prompt", help="Print a planner prompt for a benchmark."
    )
    make_prompt_parser.add_argument("--benchmark", required=True, help="Benchmark ID.")
    make_prompt_parser.add_argument(
        "--mode",
        choices=["direct-placement", "topology"],
        required=True,
        help="Planner prompt mode.",
    )
    make_prompt_parser.set_defaults(handler=_cmd_make_prompt)

    evaluate_parser = subparsers.add_parser(
        "evaluate-planner-output", help="Evaluate or archive saved planner output JSON."
    )
    evaluate_parser.add_argument("--benchmark", required=True, help="Benchmark ID.")
    evaluate_parser.add_argument(
        "--mode",
        choices=["direct-placement", "topology"],
        required=True,
        help="Planner output mode.",
    )
    evaluate_parser.add_argument(
        "--planner-output",
        type=Path,
        required=True,
        help="Path to saved planner output JSON.",
    )
    evaluate_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("examples/output/experiments"),
        help="Directory for generated experiment reports.",
    )
    evaluate_parser.set_defaults(handler=_cmd_evaluate_planner_output)

    llm_parser = subparsers.add_parser(
        "run-llm-benchmark", help="Run one benchmark through an optional LLM provider."
    )
    llm_parser.add_argument("--benchmark", required=True, help="Benchmark ID.")
    llm_parser.add_argument(
        "--mode",
        choices=["direct-placement", "topology"],
        required=True,
        help="Planner prompt mode.",
    )
    llm_parser.add_argument("--provider", default="anthropic", help="LLM provider name.")
    llm_parser.add_argument("--model", default=None, help="Provider model name.")
    llm_parser.add_argument("--max-tokens", type=int, default=4000, help="Maximum response tokens.")
    llm_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("examples/output/experiments"),
        help="Directory for generated experiment reports.",
    )
    llm_parser.set_defaults(handler=_cmd_run_llm_benchmark)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = args.handler

    try:
        return int(handler(args))
    except (json.JSONDecodeError, KeyError, OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
