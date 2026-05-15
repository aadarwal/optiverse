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
from .experiments import evaluate_planner_output, make_prompt
from .goal_parser import (
    PARSE_GOAL_PROMPT_VERSION,
    make_parse_goal_prompt,
    parse_goal_response,
    parse_goal_with_provider,
)
from .layout_compiler import (
    goal_from_planner_data,
    placement_from_planner_data,
    placements_from_planner_data,
)
from .scene_writer import build_scene_data, write_json
from .schema import ConstraintSpec, GoalSpec, Placement, RunResult, SourceSpec, TargetSpec
from .scorer import score_paths
from .validator import TableRect, ValidationIssue, ValidationResult, validate_goal

__all__ = [
    "BenchmarkSpec",
    "ConstraintSpec",
    "GoalSpec",
    "PARSE_GOAL_PROMPT_VERSION",
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
    "evaluate_planner_output",
    "get_benchmark",
    "goal_from_planner_data",
    "load_builtin_catalog",
    "make_prompt",
    "make_parse_goal_prompt",
    "parse_goal_response",
    "parse_goal_with_provider",
    "placement_from_planner_data",
    "placements_from_planner_data",
    "run_all_benchmarks",
    "run_benchmark",
    "score_paths",
    "validate_goal",
    "write_json",
]
