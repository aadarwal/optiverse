"""Headless agentic layout helpers for Optiverse."""

from .benchmarks import (
    BenchmarkSpec,
    benchmark_specs,
    get_benchmark,
    run_all_benchmarks,
    run_benchmark,
)
from .catalog import catalog_summary, load_builtin_catalog
from .compiler import compile_elements
from .scene_writer import build_scene_data, write_json
from .schema import ConstraintSpec, GoalSpec, Placement, RunResult, SourceSpec, TargetSpec
from .scorer import score_paths
from .validator import TableRect, ValidationIssue, ValidationResult, validate_goal

__all__ = [
    "BenchmarkSpec",
    "ConstraintSpec",
    "GoalSpec",
    "Placement",
    "RunResult",
    "SourceSpec",
    "TableRect",
    "TargetSpec",
    "ValidationIssue",
    "ValidationResult",
    "build_scene_data",
    "benchmark_specs",
    "catalog_summary",
    "compile_elements",
    "get_benchmark",
    "load_builtin_catalog",
    "run_all_benchmarks",
    "run_benchmark",
    "score_paths",
    "validate_goal",
    "write_json",
]
