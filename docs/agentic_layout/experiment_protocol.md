# Agentic Layout Experiment Protocol

## Goal

Compare two planner modes on the same benchmark suite:

- `direct-placement`: the model emits exact component placements.
- `topology`: the model emits qualitative topology and intent only.

This is a schema-discovery experiment. Direct placement is expected to reveal coordinate and geometry failure modes. Topology mode is expected to reveal what structure the model naturally provides before a real layout compiler exists.

## Benchmarks

Fixtures live under:

```text
examples/agentic_benchmarks/{benchmark}/
```

Generated benchmark outputs live under:

```text
examples/output/benchmarks/{benchmark}/
```

Available benchmark IDs:

- `hwp_pbs_splitter`
- `two_mirror_steering`
- `single_lens_focus`
- `four_f_telescope`
- `mach_zehnder_skeleton`

## Manual LLM Path

Generate a prompt:

```bash
.venv313/bin/python -m optiverse.agentic.cli make-prompt \
  --benchmark hwp_pbs_splitter \
  --mode direct-placement
```

Call the model externally and save its JSON output here:

```text
examples/agentic_experiments/{benchmark}/{mode}/model_output.json
```

Then evaluate it:

```bash
.venv313/bin/python -m optiverse.agentic.cli evaluate-planner-output \
  --benchmark hwp_pbs_splitter \
  --mode direct-placement \
  --planner-output examples/agentic_experiments/hwp_pbs_splitter/direct-placement/model_output.json \
  --output-dir examples/output/experiments
```

For topology mode, the evaluator archives the JSON and performs structural checks only.

## Optional Provider Path

The provider path is a convenience wrapper over the same saved-output evaluator.

For Anthropic:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...
export ANTHROPIC_MODEL=...
```

Run:

```bash
.venv313/bin/python -m optiverse.agentic.cli run-llm-benchmark \
  --benchmark hwp_pbs_splitter \
  --mode direct-placement \
  --provider anthropic \
  --output-dir examples/output/experiments
```

The command writes:

```text
examples/agentic_experiments/{benchmark}/{mode}/prompt.txt
examples/agentic_experiments/{benchmark}/{mode}/raw_response.txt
examples/agentic_experiments/{benchmark}/{mode}/provider_response.json
examples/agentic_experiments/{benchmark}/{mode}/model_output.json
examples/output/experiments/{benchmark}/{mode}/report.json
```

## Report Stages

Experiment reports distinguish:

- `schema`: JSON shape or parse errors.
- `validation`: catalog ID, override, source, target, constraint, table, or overlap errors.
- `trace`: exceptions while compiling or raytracing.
- `score`: raytrace completed but constraints failed.
- `None`: planner output passed the available evaluator checks.

Unsupported checks are listed separately in `unsupported_checks` when the scorer can detect them.
