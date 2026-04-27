"""Pipeline orchestrator: LLM → validate → solve → assemble → output."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .assembler import assemble, assembly_to_json
from .catalog import scan_library
from .client import LLMClient
from .prompts import build_system_prompt
from .solver import solve
from .topology import BeamPathSpec, validate_spec

_logger = logging.getLogger(__name__)


def generate_layout(
    user_prompt: str,
    *,
    model: str = "gpt-4o",
    temperature: float = 0.2,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    End-to-end pipeline: user prompt → optiverse v2.0 assembly JSON.

    Steps:
      1. Build system prompt (CONTEXT.md + component catalog).
      2. Call LLM with user prompt, receive beam path spec JSON.
      3. Validate the beam path spec.
      4. Solve positions and orientations.
      5. Assemble into v2.0 assembly JSON.
      6. Optionally write to file.

    Args:
        user_prompt: Natural-language description of the desired layout.
        model: OpenAI model name (default: gpt-4o).
        temperature: LLM temperature (default: 0.2 for determinism).
        output_path: If provided, write assembly JSON to this file.

    Returns:
        The v2.0 assembly dict.

    Raises:
        ValueError: If the LLM output fails validation.
        RuntimeError: If the LLM call fails.
    """
    catalog = scan_library()
    _logger.info("Loaded %d library components", len(catalog))

    system_prompt = build_system_prompt(catalog)
    _logger.info("System prompt: %d characters", len(system_prompt))

    client = LLMClient(model=model, temperature=temperature)
    raw = client.generate(system_prompt, user_prompt)
    _logger.info("LLM returned beam path spec with %d components", len(raw.get("components", [])))

    spec = BeamPathSpec.from_dict(raw)

    errors = validate_spec(spec, set(catalog.keys()))
    if errors:
        error_msg = "Beam path spec validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        _logger.error(error_msg)
        raise ValueError(error_msg)

    placed = solve(spec, catalog)
    _logger.info("Solver placed %d components", len(placed))

    assembly = assemble(placed, catalog)

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(assembly_to_json(assembly), encoding="utf-8")
        _logger.info("Assembly written to %s", output_path)

    return assembly


def generate_from_spec(
    spec_path: Path | str,
    *,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Bypass the LLM: load a beam path spec from a JSON file, solve and assemble.

    Useful for testing the solver pipeline without an API key.
    """
    spec_path = Path(spec_path)
    raw = json.loads(spec_path.read_text(encoding="utf-8"))
    spec = BeamPathSpec.from_dict(raw)

    catalog = scan_library()
    errors = validate_spec(spec, set(catalog.keys()))
    if errors:
        error_msg = "Beam path spec validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)

    placed = solve(spec, catalog)
    assembly = assemble(placed, catalog)

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(assembly_to_json(assembly), encoding="utf-8")

    return assembly
