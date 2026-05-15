# Agentic CLI And Plugin

The agentic layout path turns a natural-language optics request or a structured `GoalSpec` into a traced, scored, GUI-loadable Optiverse scene.

The design is intentionally split:

- `optiverse-agent` is the durable command surface. Each command reads and writes JSON so scripts, coding agents, and CI can compose it.
- `optiverse-agent design` is the thin built-in consumer. It parses a natural-language request, proposes placements, compiles, validates, traces, scores, renders, and optionally opens the GUI.
- `plugins/optiverse-agentic-design` is the agent-plugin consumer. It teaches a coding agent to drive the same CLI, inspect score reports, and iterate.

This is not a numerical optimizer or a general topology-graph compiler. The current compiler supports explicit placements, interface-hit anchors, and focal-length spacing primitives.

## Installation

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
optiverse-agent --help
```

In this development checkout the verified environment is `.venv313`, so local maintenance commands usually use:

```bash
.venv313/bin/optiverse-agent --help
```

## Command Surface

Use `-` as input to read JSON from stdin. Use `--output PATH` to write JSON or PNG output to a file instead of stdout when a command supports it.

| Command | Purpose |
| --- | --- |
| `catalog` | Emit the built-in component catalog with agent-readable component IDs and annotations. |
| `parse-goal` | Convert a natural-language request into `GoalSpec` JSON through a swappable provider. |
| `compile` | Convert `GoalSpec` or benchmark-wrapper JSON into GUI-loadable scene JSON. |
| `validate` | Attach validation results to a scene or goal document. |
| `trace` | Raytrace a scene and attach serialized ray paths. |
| `score` | Score traced or traceable scene JSON against targets and constraints. |
| `render` | Render a headless PNG schematic from scene JSON. |
| `open` | Launch the Optiverse GUI on a scene JSON file. |
| `design` | Run the built-in natural-language design loop end to end. |
| `run-benchmark` / `run-all-benchmarks` | Execute the built-in benchmark fixtures. |
| `make-prompt` / `evaluate-planner-output` / `run-llm-benchmark` | Run the planner-output experiment harness. |

## File Workflow

This example compiles, validates, traces, scores, and renders the HWP/PBS benchmark:

```bash
RUN_DIR=/tmp/optiverse-agentic-cli
rm -rf "$RUN_DIR"
mkdir -p "$RUN_DIR"

.venv313/bin/optiverse-agent compile \
  examples/agentic_benchmarks/hwp_pbs_splitter/goal.json \
  --output "$RUN_DIR/scene.json"

.venv313/bin/optiverse-agent validate \
  "$RUN_DIR/scene.json" \
  --output "$RUN_DIR/validated.scene.json"

.venv313/bin/optiverse-agent trace \
  "$RUN_DIR/validated.scene.json" \
  --output "$RUN_DIR/traced.scene.json"

.venv313/bin/optiverse-agent score \
  "$RUN_DIR/traced.scene.json" \
  --goal examples/agentic_benchmarks/hwp_pbs_splitter/goal.json \
  --output "$RUN_DIR/score.json"

.venv313/bin/optiverse-agent render \
  "$RUN_DIR/traced.scene.json" \
  --output "$RUN_DIR/schematic.png"
```

Check the score:

```bash
.venv313/bin/python - <<'PY'
import json
from pathlib import Path
score = json.loads(Path("/tmp/optiverse-agentic-cli/score.json").read_text())
print(score["score"]["passed"])
PY
```

The same pipeline can be piped:

```bash
.venv313/bin/optiverse-agent compile examples/agentic_benchmarks/hwp_pbs_splitter/goal.json \
  | .venv313/bin/optiverse-agent validate - \
  | .venv313/bin/optiverse-agent trace - \
  | .venv313/bin/optiverse-agent score - --goal examples/agentic_benchmarks/hwp_pbs_splitter/goal.json \
  | .venv313/bin/python -c "import json, sys; print(json.load(sys.stdin)['score']['passed'])"
```

## GoalSpec

The current `GoalSpec` JSON carries:

- `source`: beam pose, wavelength, polarization, ray count, spread, and Gaussian-beam fields.
- `placements`: selected catalog components with labels and either origin coordinates or layout-compiler anchors.
- `targets`: virtual detector points used for endpoint, power, and polarization scoring.
- `constraints`: explicit checks such as `target_hit`, `power_at_target`, `polarization_at_target`, `path_contains_elements`, `path_avoids_elements`, `path_length`, `beam_radius_at_target`, `spot_centroid_at_plane`, and `spot_rms_radius_at_plane`.
- `topology`: human-readable intent for reports and planner context.

The score report includes `ray_paths[].path_element_ids`, the interaction ledger used to distinguish which optics each ray actually hit.

## Layout Compiler Primitives

Origin-form placements remain supported:

```json
{
  "label": "PBS1",
  "catalog_id": "pbs_2in",
  "x_mm": 145.0,
  "y_mm": 0.0,
  "angle_deg": 0.0
}
```

Use an interface anchor when the planner knows the hit point rather than the Optiverse sprite origin:

```json
{
  "label": "M1",
  "catalog_id": "mirror_standard_1in",
  "angle_deg": 45.0,
  "anchor": {
    "kind": "interface_midpoint",
    "x_mm": 120.0,
    "y_mm": 0.0,
    "interface_index": 0
  }
}
```

Use focal-length spacing for simple relay/telescope plans:

```json
{
  "label": "L2",
  "catalog_id": "lens_standard_1in",
  "angle_deg": 0.0,
  "relative_to": "L1",
  "axis": "x",
  "direction": 1,
  "spacing": "f1_plus_f2"
}
```

## Natural-Language Design

Run the deterministic mock path in CI or examples:

```bash
RUN_DIR=/tmp/optiverse-design
rm -rf "$RUN_DIR"
.venv313/bin/optiverse-agent design \
  "50/50 split a 780 nm horizontally polarized beam with a HWP and PBS" \
  --provider mock \
  --no-open \
  --output-dir "$RUN_DIR" \
  --output "$RUN_DIR/design.report.json"
```

With a real provider, set the provider credentials first:

```bash
export ANTHROPIC_API_KEY=...
.venv313/bin/optiverse-agent design \
  "50/50 split a 780 nm horizontally polarized beam with a HWP and PBS" \
  --provider anthropic \
  --model <model-name> \
  --output-dir examples/output/designs/hwp-pbs
```

The `design` command retries failed plans up to `--max-rounds` and opens the GUI on success unless `--no-open` is set.

## Plugin Consumer

The plugin lives at:

```text
plugins/optiverse-agentic-design/
```

It contains:

- `.claude-plugin/plugin.json`: Claude Code plugin manifest.
- `.codex-plugin/plugin.json`: Codex-compatible plugin manifest.
- `skills/optiverse-design/SKILL.md`: workflow instructions for an agent.
- `README.md`: install and smoke-test steps.

Install the local Claude Code marketplace from the repository root:

```bash
claude plugin marketplace add ./ --scope local
claude plugin install optiverse-agentic-design@optiverse-local --scope local
```

The plugin path is the higher-leverage consumer because the coding agent owns the iteration loop: it can inspect the score JSON, adjust the `GoalSpec`, rerun the CLI chain, and call `open` only after the score passes.

## Benchmark Verification

Run all built-in agentic benchmarks:

```bash
.venv313/bin/optiverse-agent run-all-benchmarks --output-dir /tmp/optiverse-benchmarks
```

Run the local development gate:

```bash
.venv313/bin/python -m ruff check src tests
.venv313/bin/python -m mypy src/
.venv313/bin/python -m pytest tests/agentic tests/raytracing tests/core tests/integration
```

Validate plugin packaging:

```bash
claude plugin validate plugins/optiverse-agentic-design
claude plugin validate .
python3 /Users/aadarwal/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  plugins/optiverse-agentic-design/skills/optiverse-design
```

## GUI Hand-Off

Use the GUI when the scene is ready to inspect visually:

```bash
.venv313/bin/optiverse-agent open /tmp/optiverse-agentic-cli/traced.scene.json
```

Use `--no-open` for headless automation, CI, and documentation examples.
