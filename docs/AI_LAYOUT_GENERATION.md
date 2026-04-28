---
layout: default
title: AI Layout Generation
---

# AI-Powered Optical Table Layout Generation

Optiverse includes an AI module that generates optical table layouts from natural language descriptions or structured beam path specifications. It uses a two-stage architecture: an LLM generates the beam path topology, and a deterministic solver computes exact component positions and orientations.

## Architecture

The system has two stages:

1. **LLM (Stage 1)**: Takes a natural language prompt (e.g. "Mach-Zehnder interferometer with 200mm arms") and outputs a **Beam Path Specification** — a JSON topology describing which components to use, how beams connect them, at what angles and distances, and the interaction type at each component. The LLM does **not** compute x/y positions.

2. **Solver (Stage 2)**: Walks the topology graph starting from source components, propagates beam positions using the specified angles and distances, computes component orientations from the optics physics (mirror bisection angles, beam splitter ±90° reflection, etc.), and outputs an optiverse v2.0 assembly JSON file that can be opened directly in the app.

```
User Prompt
    │
    ▼
┌─────────────────┐     system prompt = CONTEXT.md
│  LLM (OpenAI)   │◄─── + component catalog
│  JSON mode       │     + interface types
└────────┬────────┘
         │ Beam Path Spec (JSON)
         ▼
┌─────────────────┐
│  Validator       │ checks IDs, library_ids, distances, reachability
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Solver          │ BFS beam propagation, orientation math,
│                  │ interface-offset correction
└────────┬────────┘
         │ Placed components (x, y, angle)
         ▼
┌─────────────────┐
│  Assembler       │ merges with library data (images, interfaces)
└────────┬────────┘
         │
         ▼
   v2.0 Assembly JSON  →  Open in Optiverse
```

## Setup

### 1. Install the AI dependency

The AI module requires the `openai` Python package, which is an optional dependency:

```bash
# If installed in editable mode:
pip install -e '.[ai]'

# Or just add the extra:
pip install 'optiverse[ai]'
```

### 2. Set your OpenAI API key

```bash
export OPENAI_API_KEY='sk-...'
```

You can add this to your shell profile (`~/.zshrc`, `~/.bashrc`) to make it permanent.

### 3. Verify the installation

```bash
python -m optiverse.ai.cli --help
```

You should see:

```
usage: optiverse-generate [-h] [--spec SPEC] [-o OUTPUT] [--model MODEL]
                          [--temperature TEMPERATURE] [-v]
                          [prompt]
```

## Usage

### Generate from a natural language prompt

```bash
python -m optiverse.ai.cli "Mach-Zehnder interferometer with 200mm arm length" -o mz.json
```

This calls the LLM, validates the output, solves positions, and writes the assembly JSON.

### Generate from a beam path spec file (no API key needed)

You can bypass the LLM entirely by writing a beam path spec JSON file manually:

```json
{
  "description": "Simple collimated beam",
  "components": [
    {"id": "src", "library_id": "source_standard", "overrides": {"n_rays": 9, "spread_deg": 5}},
    {"id": "lens1", "library_id": "lens_standard_1in", "overrides": {"efl_mm": 100}}
  ],
  "beam_paths": [
    {"from": "src", "to": "lens1", "angle_deg": 0, "distance_mm": 100}
  ]
}
```

Then run:

```bash
python -m optiverse.ai.cli --spec my_spec.json -o layout.json
```

This is useful for testing, scripting, or when you want precise control over the topology without an LLM.

### Open the result in Optiverse

The output is a standard optiverse assembly file:

```bash
optiverse
# Then: File → Open → select your .json file
```

### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `prompt` | — | Natural language description of the layout |
| `--spec FILE` | — | Beam path spec JSON file (bypasses LLM) |
| `-o, --output FILE` | stdout | Write assembly JSON to this file |
| `--model NAME` | `gpt-4o` | OpenAI model to use |
| `--temperature FLOAT` | `0.2` | LLM temperature (lower = more deterministic) |
| `-v, --verbose` | off | Print debug logging to stderr |

## Beam Path Specification Format

The topology JSON has two arrays: `components` and `beam_paths`.

### Components

```json
{
  "id": "mirror1",
  "library_id": "mirror_standard_1in",
  "overrides": {"reflectivity": 95.0}
}
```

- **`id`** — unique identifier you choose.
- **`library_id`** — must match an available library component folder name exactly.
- **`overrides`** — optional property overrides for the component's optical interface.

### Beam paths

```json
{
  "from": "bs1",
  "to": "mirror1",
  "angle_deg": 270,
  "distance_mm": 200,
  "interaction": "reflection"
}
```

- **`angle_deg`** — direction the beam travels (user convention: 0°=right, 90°=down, 180°=left, 270°=up).
- **`distance_mm`** — optical path length (must be > 0).
- **`interaction`** — how the beam leaves the `from` component:
  - `"pass_through"` (default): lenses, waveplates, polarisers.
  - `"reflection"`: mirrors, beam splitter reflected arm, SLMs.
  - `"transmission"`: beam splitter transmitted arm.

### Available library components

| library_id | Name | Category |
|------------|------|----------|
| `source_standard` | Standard Source | sources |
| `lens_standard_1in` | Standard Lens (1" mounted) | lenses |
| `lens_standard_2in` | Standard Lens (2" mounted) | lenses |
| `objective_standard` | Microscope Objective | objectives |
| `mirror_standard_1in` | Standard Mirror (1") | mirrors |
| `mirror_standard_2in` | Standard Mirror (2") | mirrors |
| `beamsplitter_50_50_1in` | 50/50 Beamsplitter (1") | beamsplitters |
| `pbs_2in` | PBS Polarising (2") | beamsplitters |
| `dichroic_550nm` | Dichroic Mirror (550nm) | dichroics |
| `waveplate_hwp` | Half Waveplate (HWP) | waveplates |
| `waveplate_qwp` | Quarter Waveplate (QWP) | waveplates |
| `linear_polarizer` | Linear Polariser | waveplates |
| `faraday_rotator` | Faraday Rotator (45°) | waveplates |
| `slm200` | Spatial Light Modulator | misc |
| `beam_block` | Beam Block | misc |
| `laser_table` | Laser Table (background) | background |
| `breadboard_mbh24` | MBH24 Breadboard (background) | background |

## Examples

### Mach-Zehnder interferometer

```json
{
  "description": "Mach-Zehnder interferometer with two arms",
  "components": [
    {"id": "src", "library_id": "source_standard", "overrides": {"n_rays": 1, "spread_deg": 0}},
    {"id": "bs_in", "library_id": "beamsplitter_50_50_1in"},
    {"id": "mirror_arm1", "library_id": "mirror_standard_1in"},
    {"id": "mirror_arm2", "library_id": "mirror_standard_1in"},
    {"id": "bs_out", "library_id": "beamsplitter_50_50_1in"},
    {"id": "detector", "library_id": "beam_block"}
  ],
  "beam_paths": [
    {"from": "src",         "to": "bs_in",        "angle_deg": 0,   "distance_mm": 150},
    {"from": "bs_in",       "to": "mirror_arm1",   "angle_deg": 0,   "distance_mm": 200, "interaction": "transmission"},
    {"from": "bs_in",       "to": "mirror_arm2",   "angle_deg": 270, "distance_mm": 200, "interaction": "reflection"},
    {"from": "mirror_arm1", "to": "bs_out",        "angle_deg": 270, "distance_mm": 200, "interaction": "reflection"},
    {"from": "mirror_arm2", "to": "bs_out",        "angle_deg": 0,   "distance_mm": 200, "interaction": "reflection"},
    {"from": "bs_out",      "to": "detector",      "angle_deg": 0,   "distance_mm": 100, "interaction": "transmission"}
  ]
}
```

### Beam expander with periscope fold

```json
{
  "description": "3x Keplerian beam expander with periscope fold",
  "components": [
    {"id": "src", "library_id": "source_standard", "overrides": {"n_rays": 9, "spread_deg": 3}},
    {"id": "collimator", "library_id": "lens_standard_1in", "overrides": {"efl_mm": 50}},
    {"id": "expander", "library_id": "lens_standard_2in", "overrides": {"efl_mm": 150}},
    {"id": "fold1", "library_id": "mirror_standard_2in"},
    {"id": "fold2", "library_id": "mirror_standard_2in"},
    {"id": "block", "library_id": "beam_block"}
  ],
  "beam_paths": [
    {"from": "src",        "to": "collimator", "angle_deg": 0,  "distance_mm": 50},
    {"from": "collimator", "to": "expander",   "angle_deg": 0,  "distance_mm": 200},
    {"from": "expander",   "to": "fold1",      "angle_deg": 0,  "distance_mm": 150},
    {"from": "fold1",      "to": "fold2",      "angle_deg": 90, "distance_mm": 200, "interaction": "reflection"},
    {"from": "fold2",      "to": "block",      "angle_deg": 0,  "distance_mm": 100, "interaction": "reflection"}
  ]
}
```

## Python API

You can also use the AI module programmatically:

```python
from optiverse.ai.generator import generate_layout, generate_from_spec

# From natural language (requires OPENAI_API_KEY):
assembly = generate_layout(
    "Collimated beam with 50mm focal length lens",
    model="gpt-4o",
    output_path="collimated.json",
)

# From a spec file (no API key needed):
assembly = generate_from_spec("my_spec.json", output_path="layout.json")
```

The solver and assembler can also be used independently:

```python
from optiverse.ai.topology import BeamPathSpec
from optiverse.ai.solver import solve
from optiverse.ai.assembler import assemble, assembly_to_json
from optiverse.ai.catalog import scan_library

catalog = scan_library()
spec = BeamPathSpec.from_dict(my_topology_dict)
placed = solve(spec, catalog)
assembly = assemble(placed, catalog)
print(assembly_to_json(assembly))
```

## Module structure

```
src/optiverse/ai/
├── __init__.py       # Package init
├── CONTEXT.md        # LLM knowledge document (physics, rules, examples)
├── topology.py       # BeamPathSpec dataclasses + validation
├── catalog.py        # Scans library, builds component catalog text
├── solver.py         # BFS position propagation + orientation math
├── assembler.py      # Converts solver output to v2.0 assembly JSON
├── prompts.py        # Builds system prompt (CONTEXT.md + catalog)
├── client.py         # OpenAI API wrapper with JSON mode
├── generator.py      # End-to-end pipeline orchestrator
└── cli.py            # CLI entrypoint
```

## Troubleshooting

**"The 'openai' package is required"**
Install the AI extra: `pip install -e '.[ai]'`

**"OPENAI_API_KEY environment variable is not set"**
Export your key: `export OPENAI_API_KEY='sk-...'`

**"Unknown library_id 'xyz'"**
The component name must match a folder in `src/optiverse/objects/library/`. Run with `-v` to see available IDs.

**"Beam path spec validation failed"**
The LLM output had structural errors. Check the error messages — common issues are duplicate component IDs, missing components in beam_paths, or unreachable components. Try rephrasing your prompt or use `--spec` with a hand-written file.

**Layout looks wrong when opened in Optiverse**
The solver computes positions from angles and distances. If components overlap or beams don't connect visually, the beam path spec likely has inconsistent angles or distances. Test with `--spec` and a known-good spec file first.
