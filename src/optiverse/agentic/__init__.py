"""Headless agentic layout helpers for Optiverse."""

from .catalog import catalog_summary, load_builtin_catalog
from .compiler import compile_elements
from .scene_writer import build_scene_data, write_json
from .schema import ConstraintSpec, GoalSpec, Placement, RunResult, SourceSpec, TargetSpec
from .scorer import score_paths

__all__ = [
    "ConstraintSpec",
    "GoalSpec",
    "Placement",
    "RunResult",
    "SourceSpec",
    "TargetSpec",
    "build_scene_data",
    "catalog_summary",
    "compile_elements",
    "load_builtin_catalog",
    "score_paths",
    "write_json",
]
