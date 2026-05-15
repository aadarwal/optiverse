"""Deterministic benchmark cases for the headless agentic layout harness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from optiverse.raytracing.engine import trace_rays_polymorphic

from .catalog import Catalog, load_builtin_catalog
from .compiler import compile_elements, interfaces_for_placement, placed_interface
from .layout_compiler import placements_from_planner_data
from .scene_writer import build_scene_data, write_json
from .schema import ConstraintSpec, GoalSpec, Placement, SourceSpec, TargetSpec
from .scorer import score_paths
from .validator import validate_goal


@dataclass(frozen=True)
class BenchmarkSpec:
    """One explicit-placement benchmark."""

    benchmark_id: str
    goal: GoalSpec
    expected_limitations: list[str]
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "goal": self.goal.to_dict(),
            "expected_limitations": list(self.expected_limitations),
            "notes": self.notes,
        }


def _placement_with_interface_midpoint(
    catalog: Catalog,
    *,
    label: str,
    catalog_id: str,
    midpoint_x_mm: float,
    midpoint_y_mm: float,
    angle_deg: float,
) -> Placement:
    """Place a component so interface 0's midpoint lands on the requested point."""
    origin_placement = Placement(
        label=label,
        catalog_id=catalog_id,
        x_mm=0.0,
        y_mm=0.0,
        angle_deg=angle_deg,
    )
    iface = placed_interface(
        interfaces_for_placement(catalog, origin_placement)[0],
        origin_placement,
    )
    iface_mid_x = 0.5 * (float(iface.x1_mm) + float(iface.x2_mm))
    iface_mid_y = 0.5 * (float(iface.y1_mm) + float(iface.y2_mm))
    return Placement(
        label=label,
        catalog_id=catalog_id,
        x_mm=midpoint_x_mm - iface_mid_x,
        y_mm=midpoint_y_mm - iface_mid_y,
        angle_deg=angle_deg,
    )


def _hwp_pbs_splitter(_catalog: Catalog) -> BenchmarkSpec:
    goal = GoalSpec(
        goal_id="hwp_pbs_splitter",
        description=(
            "Horizontally polarized 780 nm beam is rotated by an HWP at 22.5 degrees "
            "and split by a PBS into horizontal and vertical detector arms."
        ),
        topology="source -> HWP1 -> PBS1 -> {transmitted: D1, reflected: D2}",
        source=SourceSpec(ray_length_mm=500.0, n_rays=1, size_mm=0.0),
        placements=[
            Placement(
                label="HWP1",
                catalog_id="waveplate_hwp",
                x_mm=60.0,
                y_mm=0.0,
                interface_overrides={0: {"fast_axis_deg": 22.5}},
            ),
            Placement(label="PBS1", catalog_id="pbs_2in", x_mm=145.0, y_mm=0.0),
        ],
        targets=[
            TargetSpec(
                name="D1_transmitted_H",
                x_mm=300.0,
                y_mm=0.0,
                radius_mm=2.0,
                polarization="horizontal",
                expected_power_fraction=0.5,
            ),
            TargetSpec(
                name="D2_reflected_V",
                x_mm=145.0,
                y_mm=-250.0,
                radius_mm=2.0,
                polarization="vertical",
                expected_power_fraction=0.5,
            ),
        ],
        constraints=[
            ConstraintSpec(kind="branch_count", params={"expected": 2}),
            ConstraintSpec(
                kind="path_contains_elements",
                params={
                    "target": "D1_transmitted_H",
                    "elements": ["HWP1:iface0", "PBS1:iface0"],
                },
            ),
            ConstraintSpec(
                kind="path_contains_elements",
                params={
                    "target": "D2_reflected_V",
                    "elements": ["HWP1:iface0", "PBS1:iface0"],
                },
            ),
        ],
    )
    return BenchmarkSpec(
        benchmark_id=goal.goal_id,
        goal=goal,
        expected_limitations=[],
        notes="Polarization/routing benchmark; a single geometric ray is sufficient.",
    )


def _two_mirror_steering(catalog: Catalog) -> BenchmarkSpec:
    placements = placements_from_planner_data(
        catalog,
        [
            {
                "label": "M1",
                "catalog_id": "mirror_standard_1in",
                "angle_deg": 45.0,
                "anchor": {"kind": "interface_midpoint", "x_mm": 50.0, "y_mm": 0.0},
            },
            {
                "label": "M2",
                "catalog_id": "mirror_standard_1in",
                "angle_deg": 45.0,
                "anchor": {"kind": "interface_midpoint", "x_mm": 50.0, "y_mm": 100.0},
            },
        ],
    )
    goal = GoalSpec(
        goal_id="two_mirror_steering",
        description="Two mirrors steer a single horizontal beam around a 90 degree corner.",
        topology="source -> M1 -> M2 -> D_corner",
        source=SourceSpec(ray_length_mm=300.0, n_rays=1, size_mm=0.0),
        placements=placements,
        targets=[
            TargetSpec(
                name="D_corner",
                x_mm=200.0,
                y_mm=100.0,
                radius_mm=2.0,
                polarization="horizontal",
                expected_power_fraction=1.0,
            )
        ],
        constraints=[
            ConstraintSpec(kind="branch_count", params={"expected": 1}),
            ConstraintSpec(
                kind="path_contains_elements",
                params={"target": "D_corner", "elements": ["M1:iface0", "M2:iface0"]},
            ),
            ConstraintSpec(kind="path_avoids_elements", params={"elements": ["BLOCK:iface0"]}),
        ],
    )
    return BenchmarkSpec(
        benchmark_id=goal.goal_id,
        goal=goal,
        expected_limitations=[],
        notes="Routing benchmark with no branching and no Gaussian propagation.",
    )


def _single_lens_focus(_catalog: Catalog) -> BenchmarkSpec:
    goal = GoalSpec(
        goal_id="single_lens_focus",
        description="A seven-ray parallel bundle crosses the optical axis at a lens focal plane.",
        topology="parallel bundle -> L1 -> focal plane at x=200 mm",
        source=SourceSpec(
            x_mm=0.0,
            y_mm=0.0,
            angle_deg=0.0,
            size_mm=12.0,
            n_rays=7,
            ray_length_mm=250.0,
            spread_deg=0.0,
        ),
        placements=[Placement(label="L1", catalog_id="lens_standard_1in", x_mm=100.0, y_mm=0.0)],
        targets=[],
        constraints=[
            ConstraintSpec(
                kind="path_contains_elements",
                params={"elements": ["L1:iface0"], "mode": "all_paths"},
            ),
            ConstraintSpec(
                kind="spot_centroid_at_plane",
                params={
                    "axis": "x",
                    "value_mm": 200.0,
                    "expected_x_mm": 200.0,
                    "expected_y_mm": 0.0,
                    "tolerance_mm": 0.1,
                },
            ),
            ConstraintSpec(
                kind="spot_rms_radius_at_plane",
                params={"axis": "x", "value_mm": 200.0, "max_mm": 0.2},
            ),
        ],
    )
    return BenchmarkSpec(
        benchmark_id=goal.goal_id,
        goal=goal,
        expected_limitations=[
            "Uses geometric bundle crossing, not diffraction-limited Gaussian focus.",
            "Spot RMS is measured at a plane from ray intersections.",
        ],
    )


def _four_f_telescope(catalog: Catalog) -> BenchmarkSpec:
    placements = placements_from_planner_data(
        catalog,
        [
            {
                "label": "L1",
                "catalog_id": "lens_standard_1in",
                "anchor": {"kind": "interface_midpoint", "x_mm": 100.0, "y_mm": 0.0},
            },
            {
                "label": "L2",
                "catalog_id": "lens_standard_1in",
                "anchor": {
                    "kind": "interface_midpoint",
                    "relative_to": "L1",
                    "spacing": "f1_plus_f2",
                    "axis": "x",
                },
            },
        ],
    )
    goal = GoalSpec(
        goal_id="four_f_telescope",
        description=(
            "Two f=100 mm lenses are separated by f1+f2 and relay a finite-height "
            "parallel bundle with inversion."
        ),
        topology="parallel bundle -> L1 -> shared focus -> L2 -> collimated output",
        source=SourceSpec(size_mm=12.0, n_rays=7, ray_length_mm=500.0, spread_deg=0.0),
        placements=placements,
        targets=[],
        constraints=[
            ConstraintSpec(
                kind="path_contains_elements",
                params={"elements": ["L1:iface0", "L2:iface0"], "mode": "all_paths"},
            ),
            ConstraintSpec(
                kind="spot_centroid_at_plane",
                params={
                    "axis": "x",
                    "value_mm": 450.0,
                    "expected_x_mm": 450.0,
                    "expected_y_mm": 0.0,
                    "tolerance_mm": 0.1,
                },
            ),
            ConstraintSpec(
                kind="spot_rms_radius_at_plane",
                params={
                    "axis": "x",
                    "value_mm": 450.0,
                    "expected_mm": 4.0,
                    "tolerance_mm": 0.1,
                },
            ),
        ],
    )
    return BenchmarkSpec(
        benchmark_id=goal.goal_id,
        goal=goal,
        expected_limitations=[
            "Confirms geometric relay size and centroid, not wave-optics imaging quality.",
            "Does not yet score output angle collimation explicitly.",
        ],
    )


def _mach_zehnder_skeleton(catalog: Catalog) -> BenchmarkSpec:
    placements = [
        Placement(
            label="BS1",
            catalog_id="beamsplitter_50_50_1in",
            x_mm=100.0,
            y_mm=0.0,
            angle_deg=90.0,
        ),
        _placement_with_interface_midpoint(
            catalog,
            label="MT",
            catalog_id="mirror_standard_1in",
            midpoint_x_mm=200.0,
            midpoint_y_mm=0.0,
            angle_deg=45.0,
        ),
        _placement_with_interface_midpoint(
            catalog,
            label="MR",
            catalog_id="mirror_standard_1in",
            midpoint_x_mm=100.0,
            midpoint_y_mm=100.0,
            angle_deg=45.0,
        ),
    ]
    goal = GoalSpec(
        goal_id="mach_zehnder_skeleton",
        description=(
            "A 50/50 beamsplitter creates two arms with one mirror in each arm. "
            "This is a routing skeleton, not a recombining interferometer."
        ),
        topology="source -> BS1 -> {transmitted: MT, reflected: MR}",
        source=SourceSpec(ray_length_mm=400.0, n_rays=1, size_mm=0.0),
        placements=placements,
        targets=[],
        constraints=[
            ConstraintSpec(kind="branch_count", params={"expected": 2}),
            ConstraintSpec(
                kind="path_contains_elements",
                params={"elements": ["BS1:iface0", "MT:iface0"]},
            ),
            ConstraintSpec(
                kind="path_contains_elements",
                params={"elements": ["BS1:iface0", "MR:iface0"]},
            ),
        ],
    )
    return BenchmarkSpec(
        benchmark_id=goal.goal_id,
        goal=goal,
        expected_limitations=[
            "Does not model phase or interference at recombination.",
            "Minimal path_element_ids distinguish arms, but no transmitted/reflected labels exist.",
            "No optical path length equality constraint is scored yet.",
        ],
    )


def benchmark_specs(catalog: Catalog | None = None) -> dict[str, BenchmarkSpec]:
    """Return all built-in benchmark specs keyed by benchmark ID."""
    catalog = catalog or load_builtin_catalog()
    specs = [
        _hwp_pbs_splitter(catalog),
        _two_mirror_steering(catalog),
        _single_lens_focus(catalog),
        _four_f_telescope(catalog),
        _mach_zehnder_skeleton(catalog),
    ]
    return {spec.benchmark_id: spec for spec in specs}


def get_benchmark(benchmark_id: str, catalog: Catalog | None = None) -> BenchmarkSpec:
    """Return one benchmark spec by ID."""
    specs = benchmark_specs(catalog)
    if benchmark_id not in specs:
        known = ", ".join(sorted(specs))
        raise KeyError(f"Unknown benchmark '{benchmark_id}'. Known benchmarks: {known}")
    return specs[benchmark_id]


def run_benchmark(
    benchmark_id: str, *, output_dir: Path, catalog: Catalog | None = None
) -> dict[str, Any]:
    """Run one benchmark and write deterministic scene/report artifacts."""
    catalog = catalog or load_builtin_catalog()
    spec = get_benchmark(benchmark_id, catalog)
    validation = validate_goal(spec.goal, catalog)
    paths = []
    score = {
        "target_scores": {},
        "constraint_scores": [],
        "passed": False,
        "ray_paths": [],
    }

    if validation.passed:
        elements = compile_elements(catalog, spec.goal.placements)
        paths = trace_rays_polymorphic(
            elements,
            [spec.goal.source.to_source_params()],
            parallel=False,
            min_intensity=0.0,
        )
        score = score_paths(paths, spec.goal.targets, spec.goal.constraints)

    benchmark_dir = output_dir / spec.benchmark_id
    scene_path = benchmark_dir / "scene.json"
    report_path = benchmark_dir / "report.json"
    goal_path = benchmark_dir / "goal.json"
    placements_path = benchmark_dir / "explicit_placements.json"

    write_json(goal_path, spec.to_dict())
    write_json(
        placements_path,
        {
            "benchmark_id": spec.benchmark_id,
            "placements": [placement.to_dict() for placement in spec.goal.placements],
        },
    )
    write_json(scene_path, build_scene_data(catalog, spec.goal))

    report = {
        "benchmark_id": spec.benchmark_id,
        "description": spec.goal.description,
        "expected_limitations": spec.expected_limitations,
        "validation": validation.to_dict(),
        "path_count": len(paths),
        "score": score,
        "output_files": {
            "goal": str(goal_path),
            "placements": str(placements_path),
            "scene": str(scene_path),
            "report": str(report_path),
        },
    }
    write_json(report_path, report)

    return report


def run_all_benchmarks(*, output_dir: Path, catalog: Catalog | None = None) -> dict[str, Any]:
    """Run all built-in benchmarks and write a summary."""
    catalog = catalog or load_builtin_catalog()
    reports = [
        run_benchmark(benchmark_id, output_dir=output_dir, catalog=catalog)
        for benchmark_id in sorted(benchmark_specs(catalog))
    ]
    summary = {
        "passed": all(
            report["score"]["passed"] and report["validation"]["passed"]
            for report in reports
        ),
        "benchmarks": [
            {
                "benchmark_id": report["benchmark_id"],
                "passed": report["score"]["passed"],
                "validation_passed": report["validation"]["passed"],
                "path_count": report["path_count"],
                "expected_limitations": report["expected_limitations"],
            }
            for report in reports
        ],
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def export_benchmark_fixtures(
    *, output_dir: Path, catalog: Catalog | None = None
) -> dict[str, Any]:
    """Write benchmark goal and placement fixtures without tracing them."""
    catalog = catalog or load_builtin_catalog()
    exported = []
    for benchmark_id, spec in sorted(benchmark_specs(catalog).items()):
        benchmark_dir = output_dir / benchmark_id
        goal_path = benchmark_dir / "goal.json"
        placements_path = benchmark_dir / "explicit_placements.json"
        write_json(goal_path, spec.to_dict())
        write_json(
            placements_path,
            {
                "benchmark_id": benchmark_id,
                "placements": [placement.to_dict() for placement in spec.goal.placements],
            },
        )
        exported.append(
            {
                "benchmark_id": benchmark_id,
                "goal": str(goal_path),
                "placements": str(placements_path),
            }
        )
    summary = {"benchmarks": exported}
    write_json(output_dir / "index.json", summary)
    return summary
