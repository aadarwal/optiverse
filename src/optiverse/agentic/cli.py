"""Command-line entry points for the headless agentic layout harness."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from optiverse.raytracing.engine import trace_rays_polymorphic

from .catalog import catalog_summary, load_builtin_catalog
from .compiler import compile_elements
from .scene_writer import build_scene_data, write_json
from .schema import demo_goal_spec
from .scorer import score_paths
from .validator import validate_goal


def run_demo(output_dir: Path) -> dict:
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


def print_demo_result(result: dict) -> None:
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Headless agentic Optiverse layout tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo_parser = subparsers.add_parser("demo", help="Run the HWP/PBS proof-of-concept.")
    demo_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("examples/output"),
        help="Directory for generated scene/report files.",
    )

    catalog_parser = subparsers.add_parser("catalog", help="Export the built-in catalog summary.")
    catalog_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the catalog summary JSON.",
    )

    args = parser.parse_args(argv)

    if args.command == "demo":
        result = run_demo(args.output_dir)
        print_demo_result(result)
        return 0 if result["score"]["passed"] else 1

    if args.command == "catalog":
        write_json(args.output, catalog_summary(load_builtin_catalog()))
        print(f"catalog: {args.output}")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
