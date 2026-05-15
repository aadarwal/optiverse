---
name: optiverse-design
description: Drive Optiverse optical-layout design through the optiverse-agent CLI. Use when asked to design, compile, validate, trace, score, render, open, or iterate an Optiverse optical experiment from natural language, a GoalSpec JSON document, or planner JSON.
---

# Optiverse Design

Use this skill from the Optiverse repository root. Treat `optiverse-agent` as the only integration surface: do not reach into private Python APIs unless the user asks to modify Optiverse itself.

## Setup Check

Prefer the checked-in virtual environment:

```bash
.venv313/bin/optiverse-agent --help
```

If the console script is missing, install the project editable into that environment:

```bash
.venv313/bin/python -m pip install -e .
```

Use a run directory for artifacts:

```bash
RUN_DIR=examples/output/agentic_runs/<short-slug>
mkdir -p "$RUN_DIR"
```

## Fast Baseline

For known natural-language requests, start with the thin orchestrator to get a baseline scene, score, and render:

```bash
.venv313/bin/optiverse-agent design \
  "50/50 split a 780 nm horizontally polarized beam with a HWP and PBS" \
  --provider mock \
  --no-open \
  --output-dir "$RUN_DIR" \
  --output "$RUN_DIR/design.report.json"
```

Use `--provider anthropic --model <model>` only when the user wants a live model run and the environment has `ANTHROPIC_API_KEY`. Always keep `--no-open` in tests, CI, or headless runs.

## Agentic Loop

When the user wants the coding agent to design the layout, use the composable commands directly.

1. Inspect available components and IDs:

```bash
.venv313/bin/optiverse-agent catalog --output "$RUN_DIR/catalog.json"
```

Common IDs include `source_standard`, `mirror_standard_1in`, `lens_standard_1in`, `waveplate_hwp`, `waveplate_qwp`, `pbs_2in`, `beamsplitter_50_50_1in`, `linear_polarizer`, and `beam_block`.

2. Write a `GoalSpec` JSON file. Include:

- `source`: wavelength, polarization, ray count, beam spread, and starting pose.
- `placements`: selected catalog components with labels and either origins or anchors.
- `targets`: virtual detector points with radius, expected power, and polarization.
- `constraints`: checks the score report should enforce.

Use anchor-form placement when the planner specifies where a beam should hit an optic:

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

Use relative focal spacing for lens relays instead of guessing coordinates:

```json
{
  "label": "L2",
  "catalog_id": "lens_standard_1in",
  "angle_deg": 0.0,
  "anchor": {
    "kind": "interface_midpoint",
    "relative_to": "L1",
    "axis": "x",
    "direction": 1,
    "spacing": "f1_plus_f2"
  }
}
```

3. Compile, validate, trace, score, and render:

```bash
.venv313/bin/optiverse-agent compile "$RUN_DIR/goal.json" --output "$RUN_DIR/scene.json"
.venv313/bin/optiverse-agent validate "$RUN_DIR/scene.json" --output "$RUN_DIR/validated.scene.json"
.venv313/bin/optiverse-agent trace "$RUN_DIR/validated.scene.json" --output "$RUN_DIR/traced.scene.json"
.venv313/bin/optiverse-agent score "$RUN_DIR/traced.scene.json" --goal "$RUN_DIR/goal.json" --output "$RUN_DIR/score.json"
.venv313/bin/optiverse-agent render "$RUN_DIR/traced.scene.json" --output "$RUN_DIR/schematic.png"
```

Piping is also supported:

```bash
.venv313/bin/optiverse-agent compile "$RUN_DIR/goal.json" \
  | .venv313/bin/optiverse-agent validate - \
  | .venv313/bin/optiverse-agent trace - \
  | .venv313/bin/optiverse-agent score - --goal "$RUN_DIR/goal.json"
```

4. Read the score and trace before deciding the next edit:

- `passed`: overall answer.
- `target_scores`: nearest point, hit/miss, power fraction, and polarization overlap per detector.
- `constraint_scores`: explicit failures such as `target_hit`, `power_at_target`, `polarization_at_target`, `path_contains_elements`, `path_length`, `spot_centroid_at_plane`, and `spot_rms_radius_at_plane`.
- `ray_paths[].path_element_ids`: actual element-interaction ledger, useful for distinguishing transmitted, reflected, and stray paths.

5. Iterate the `GoalSpec`, not the scene JSON, unless debugging the compiler itself. Re-run the full chain after each meaningful edit.

## Failure Triage

- If rays miss every optic, convert origin placements to `interface_midpoint` anchors or correct the optic orientation.
- If a ray hits the wrong path, inspect `path_element_ids` and add or adjust `path_contains_elements` constraints.
- If power is wrong at a PBS, check HWP `fast_axis_deg`; a 50/50 H/V split usually uses 22.5 deg for a horizontal input.
- If polarization is wrong, adjust waveplate or polarizer parameters before moving components.
- If a focusing or relay benchmark is unstable, raise `source.n_rays` and use spot constraints at the target plane.
- If the layout looks correct but scoring fails, compare target radius, detector coordinates, and expected power tolerance.

## GUI Hand-Off

Open the GUI only after the design passes scoring, or when the user explicitly asks for a preview:

```bash
.venv313/bin/optiverse-agent open "$RUN_DIR/traced.scene.json"
```

Do not call `open` in automated tests, CI, or headless sessions. Use `render` for those environments.
