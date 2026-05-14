# Optiverse Agentic Layout Plan

## Completion Target

Build a headless agentic-layout harness for Optiverse that can:

1. Load and summarize the component catalog.
2. Accept structured optical goals and constraints.
3. Compile explicit placements into raytracing elements and GUI-loadable scene JSON.
4. Score traced rays against reusable constraints.
5. Run a small benchmark suite.
6. Compare two planner modes:
   - LLM emits direct component placements.
   - LLM emits topology/intent only.
7. Produce a data-backed recommendation for `TopologyPlan`, port metadata, and the first real `LayoutCompiler`.

The completion of this plan is **not** a full inverse-design/autoplacement system. The goal is to build the low-risk scaffold first, run the planner experiment, and use the observed failures to design the high-risk layout compiler correctly.

## Core Thesis

The split of labor should be:

- LLM: qualitative/textbook optical reasoning, experiment intent, component sequence, artifact-level parameters such as HWP angle or lens focal length.
- Deterministic code: coordinates, rotations, geometry, collision checks, scene writing.
- Optiverse raytracer: physical verification.
- Trace scorer: explicit pass/fail criteria and failure taxonomy.

Do not let the LLM act as the raytracer. Do not ask the LLM to own precise 2D coordinates as the primary strategy. Direct-coordinate output should be tested as a baseline/failure mode, not trusted as the product architecture.

## Non-Negotiable Engineering Rules

- Keep the headless pipeline out of `optiverse.ui` and `optiverse.app`.
- Do not import `MainWindow`, `SceneFileManager`, or Qt scene objects in the headless package.
- Use pure Python/data/raytracing modules wherever possible.
- Preserve existing user changes. Always inspect `git status --short` before staging.
- Stage only files intentionally changed for the current milestone.
- Commit and push at every milestone checkpoint.
- Push to `origin`, not `upstream`, unless explicitly instructed otherwise.
- If commit signing blocks on 1Password/GPG/SSH signing, use `git commit --no-gpg-sign ...` for local commits and document that choice.
- If pushing is blocked by credentials or network, do not spin forever; record the blocker, keep the local commit, and continue.

Current local note: at the time this plan was written, there were unrelated modified files in:

- `src/optiverse/objects/views/image_canvas.py`
- `tests/core/test_interface_based_raytracing.py`
- `tests/ui/test_component_editor.py`
- `tests/ui/test_component_save_guards.py`

Do not include those in agentic-layout commits unless they are explicitly brought into scope.

## Repository Starting Point

There is already a committed proof of concept:

- `examples/agentic_layout_demo.py`
- `examples/output/agentic_hwp_pbs.catalog.json`
- `examples/output/agentic_hwp_pbs.report.json`
- `examples/output/agentic_hwp_pbs.scene.json`

Commit:

```text
bc48f60 Add headless agentic layout demo
```

The demo proves that Optiverse can run a CLI-first loop:

```text
catalog -> explicit placements -> raytrace -> score -> scene JSON
```

The next work is to turn this demo into package code and then use it to run schema-discovery experiments.

## Milestone 0: Branch, Environment, And Baseline

Purpose: establish a clean branch and confirm the committed demo still works.

Steps:

1. Check status:

   ```bash
   git status --short
   git branch --show-current
   ```

2. Create a feature branch if still on `main`:

   ```bash
   git switch -c agentic-layout-harness
   ```

   If dirty unrelated files prevent switching, do not revert them. Either keep working on the current branch with careful staging or ask for direction.

3. Use Python 3.13 environment already proven in this repo:

   ```bash
   .venv313/bin/python --version
   .venv313/bin/python -m ruff --version
   ```

4. Run the existing demo:

   ```bash
   .venv313/bin/python examples/agentic_layout_demo.py --output-dir examples/output
   .venv313/bin/python -m ruff check examples/agentic_layout_demo.py
   ```

Acceptance criteria:

- Demo prints `passed: True`.
- Ruff passes for the demo.
- No new files are created except reproducible outputs already under `examples/output`.

Commit/push:

- Usually no commit is needed for Milestone 0 unless branch or docs are changed.
- Push branch once it exists:

  ```bash
  git push -u origin agentic-layout-harness
  ```

## Milestone 1: Extract The Demo Into `optiverse.agentic`

Purpose: create a reusable headless package without changing the GUI.

Create:

```text
src/optiverse/agentic/__init__.py
src/optiverse/agentic/catalog.py
src/optiverse/agentic/schema.py
src/optiverse/agentic/compiler.py
src/optiverse/agentic/scene_writer.py
src/optiverse/agentic/scorer.py
src/optiverse/agentic/cli.py
tests/agentic/
```

Responsibilities:

- `catalog.py`
  - Load built-in component JSON.
  - Preserve catalog IDs such as `waveplate_hwp`, `pbs_2in`.
  - Produce model-facing summaries.
  - Avoid Qt path APIs where possible.

- `schema.py`
  - Define serializable dataclasses for:
    - `Placement`
    - `SourceSpec`
    - `TargetSpec`
    - `GoalSpec`
    - `ConstraintSpec`
    - `RunResult`
  - Keep this schema intentionally small. Do not design full `TopologyPlan` yet.

- `compiler.py`
  - Compile explicit placements into polymorphic raytracing elements.
  - Own coordinate transforms currently in the demo.
  - Support `interface_overrides`.
  - Do not attempt topology-to-layout compilation yet.

- `scene_writer.py`
  - Write version `2.0` Optiverse assembly JSON directly.
  - Use deterministic UUIDs, preferably `uuid.uuid5`, based on stable labels and goal IDs.
  - Write source and component items compatible with the GUI loader.

- `scorer.py`
  - Initially move the demo scorer here.
  - Score `RayPath` outputs without modifying the raytracer.

- `cli.py`
  - Provide a small CLI for catalog export, running a goal, and writing scene/report files.

Also update packaging if needed. Current `pyproject.toml` uses explicit package configuration. Verify that new subpackages are included in editable and wheel-style installs. Prefer package discovery if appropriate:

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

Only make this packaging change if tests/imports show it is needed, but check it deliberately.

Keep `examples/agentic_layout_demo.py` as a thin compatibility wrapper or update it to call the new package.

Acceptance criteria:

- This works:

  ```bash
  .venv313/bin/python -m optiverse.agentic.cli demo --output-dir examples/output
  ```

- Existing demo still works:

  ```bash
  .venv313/bin/python examples/agentic_layout_demo.py --output-dir examples/output
  ```

- Unit tests cover catalog load, placement compilation, scene writing, and demo scoring.

Suggested verification:

```bash
.venv313/bin/python -m ruff check src/optiverse/agentic tests/agentic examples/agentic_layout_demo.py
.venv313/bin/python -m pytest tests/agentic
.venv313/bin/python examples/agentic_layout_demo.py --output-dir examples/output
```

Commit/push:

```bash
git status --short
git add src/optiverse/agentic tests/agentic examples/agentic_layout_demo.py pyproject.toml
git commit --no-gpg-sign -m "Extract headless agentic layout package"
git push
```

Stage `pyproject.toml` only if it actually changed.

## Milestone 2: Constraint-Oriented Goal Schema And TraceScorer

Purpose: make the verifier real before making the planner smart.

Design the goal schema around constraints, not just destinations.

Implement constraint types for v1:

- `target_hit`
  - target point or circle.
  - allowed distance tolerance.

- `power_at_target`
  - expected fraction.
  - absolute or relative tolerance.

- `polarization_at_target`
  - expected basis: `horizontal`, `vertical`, `linear_angle`, optional Jones vector later.
  - minimum overlap.

- `branch_count`
  - expected number of output ray paths above intensity threshold.

- `path_length`
  - geometric path length for now.
  - explicitly mark as not optical path length.

- `beam_radius_at_target`
  - use `RayPath.beam_radii` if present.
  - return `unsupported` if no Gaussian beam data exists.

Scoring result should include:

- per-constraint `passed`
- numerical values
- matched ray/path index
- warning messages
- unsupported checks
- aggregate pass/fail

Do not modify the raytracing engine yet. Work from current `RayPath`:

- `points`
- `intensities`
- `polarization`
- `polarizations`
- `beam_radii`
- `source_index`

Document limitations:

- No branch identity.
- No transmitted/reflected labels.
- No interaction ledger.
- No termination reason.
- No optical path length.

Acceptance criteria:

- The HWP/PBS demo is expressed as a `GoalSpec` with constraints.
- The scorer reproduces the current result:
  - D1 hit true, power 0.5, horizontal overlap 1.
  - D2 hit true, power 0.5, vertical overlap 1.
- Tests include at least:
  - exact hit
  - near miss
  - wrong power
  - wrong polarization
  - missing Gaussian data for beam-radius constraint

Suggested verification:

```bash
.venv313/bin/python -m ruff check src/optiverse/agentic tests/agentic
.venv313/bin/python -m pytest tests/agentic
.venv313/bin/python -m optiverse.agentic.cli demo --output-dir examples/output
```

Commit/push:

```bash
git status --short
git add src/optiverse/agentic tests/agentic examples/output docs
git commit --no-gpg-sign -m "Add constraint-based trace scoring"
git push
```

Only stage generated outputs/docs if they changed intentionally.

## Milestone 3: Validator And Catalog Capability Summaries

Purpose: catch invalid plans before raytracing and give LLMs better catalog context.

Implement `validator.py` or equivalent.

Validation checks:

- Catalog ID exists.
- Component has required interfaces.
- Interface override index exists.
- Override field is plausible for that interface type.
- Placement has finite `x_mm`, `y_mm`, `angle_deg`.
- Components are within an optional table rectangle.
- Approximate component footprint does not overlap another footprint.
- Scene JSON can be generated.
- Required source fields are valid.
- Constraint targets have valid tolerances.

Implement catalog summaries that include:

- `catalog_id`
- display name
- category
- object height
- interface types
- relevant optical parameters:
  - `efl_mm`
  - `clear_aperture_mm`
  - `phase_shift_deg`
  - `fast_axis_deg`
  - `split_T`
  - `split_R`
  - `is_polarizing`
  - `pbs_transmission_axis_deg`
  - `cutoff_wavelength_nm`
- inferred capabilities:
  - `source`
  - `pass_through`
  - `reflects`
  - `splits`
  - `polarization_control`
  - `absorbs`
  - `focuses`

Do not add full port metadata to component JSON yet. For now, document that ports are derived/experimental.

Acceptance criteria:

- Invalid catalog IDs fail before raytracing.
- Invalid interface overrides fail before raytracing.
- Basic overlap checks work with conservative bounding boxes.
- Catalog summary is stable and deterministic.
- LLM-facing catalog export exists:

  ```bash
  .venv313/bin/python -m optiverse.agentic.cli catalog --output examples/output/catalog_summary.json
  ```

Commit/push:

```bash
git status --short
git add src/optiverse/agentic tests/agentic examples/output docs
git commit --no-gpg-sign -m "Add agentic plan validation and catalog summaries"
git push
```

## Milestone 4: Benchmark Suite

Purpose: create a small, repeatable evaluation set before involving LLMs.

Create benchmark fixtures under one of:

```text
examples/agentic_benchmarks/
tests/agentic/fixtures/
```

Required benchmark cases:

1. `hwp_pbs_splitter`
   - Goal: H input, HWP 22.5 deg, PBS split into H/V arms.
   - Checks: two branches, 50/50 power, correct polarizations, detector hits.

2. `two_mirror_steering`
   - Goal: steer a beam around a corner to a target.
   - Checks: target hit, no extra branch, sufficient power.

3. `single_lens_focus`
   - Goal: focus/cross optical axis at a target plane.
   - Checks: ray bundle narrows or crosses near expected target.
   - Be explicit about approximation limits.

4. `four_f_telescope`
   - Goal: two lenses separated by `f1 + f2`.
   - Checks: component spacing, output ray geometry, target plane behavior.

5. `mach_zehnder_skeleton`
   - Goal: beamsplitter -> two arms -> recombination/targets.
   - Checks: branch count, approximate arm geometry, equal geometric path length if possible.
   - This may expose current engine/scorer limitations. That is acceptable and useful.

Each benchmark should have:

- `goal.json`
- `explicit_placements.json`
- expected report or constraints
- generated scene/report outputs in a deterministic output directory

Add CLI:

```bash
.venv313/bin/python -m optiverse.agentic.cli run-benchmark hwp_pbs_splitter --output-dir examples/output/benchmarks
.venv313/bin/python -m optiverse.agentic.cli run-all-benchmarks --output-dir examples/output/benchmarks
```

Acceptance criteria:

- At least first three benchmarks pass with explicit placements.
- Cases that are intentionally limited are marked with clear `expected_limitations`.
- Benchmark output is deterministic enough for tests or snapshot-lite assertions.

Commit/push:

```bash
git status --short
git add src/optiverse/agentic tests/agentic examples/agentic_benchmarks examples/output docs
git commit --no-gpg-sign -m "Add agentic optical layout benchmarks"
git push
```

## Milestone 5: LLM Experiment Harness

Purpose: empirically discover what schema the model naturally emits and what failures the compiler must compensate for.

Do not hardwire a specific LLM provider as a required dependency yet. The first version can use saved JSON files as planner outputs. Provider integrations can be optional.

Create:

```text
docs/agentic_layout/prompts/
docs/agentic_layout/experiment_protocol.md
examples/agentic_experiments/
```

Prompt modes:

1. Direct-placement prompt:
   - Give goal and catalog summary.
   - Ask model to emit full placements: component IDs, x/y, angle, parameter overrides.

2. Topology/intent prompt:
   - Give goal and catalog summary.
   - Ask model to emit qualitative topology and artifact-level parameters only.
   - It may mention ports if it wants, but do not force a final schema yet.

3. Critic prompt:
   - Give report/scorer failures.
   - Ask model to explain likely issue and suggest revised plan.
   - Keep this separate from deterministic scoring.

The harness should support:

```bash
.venv313/bin/python -m optiverse.agentic.cli evaluate-planner-output \
  --benchmark hwp_pbs_splitter \
  --mode direct-placement \
  --planner-output examples/agentic_experiments/hwp_pbs/direct/model_output.json \
  --output-dir examples/output/experiments
```

For topology/intent mode, initially only validate and archive the output. Do not build a full topology compiler yet. The point is to inspect the data.

If an LLM API is available, add an optional command such as:

```bash
.venv313/bin/python -m optiverse.agentic.cli make-prompt --benchmark hwp_pbs_splitter --mode topology
```

Then the user or another process can call the model. Avoid adding a required network dependency until the project explicitly chooses one.

Acceptance criteria:

- Prompts exist and are versioned.
- The harness can evaluate saved direct-placement JSON against benchmarks.
- The harness can archive topology/intent JSON and run structural validation.
- Reports distinguish:
  - schema errors
  - invalid catalog selections
  - invalid geometry
  - trace failures
  - score failures
  - unsupported checks

Commit/push:

```bash
git status --short
git add src/optiverse/agentic docs/agentic_layout examples/agentic_experiments tests/agentic
git commit --no-gpg-sign -m "Add planner experiment harness"
git push
```

## Milestone 6: Run Experiments And Write Findings

Purpose: decide the next schema from observed model behavior, not guesses.

Run each benchmark through both prompt modes where possible:

- direct placement
- topology/intent

For each output, record:

- Did JSON parse?
- Did it match requested schema?
- Did it pick valid catalog IDs?
- Did it choose correct optical components?
- Did it choose correct artifact-level parameters?
- If direct placement:
  - Did generated coordinates validate?
  - Did raytrace pass?
  - What failed?
- If topology/intent:
  - What abstraction did the model naturally use?
  - Did it mention ports?
  - Did it mention constraints?
  - Did it omit necessary data?
  - Did it include useful physics annotations?

Write:

```text
docs/agentic_layout/experiment_report.md
docs/agentic_layout/topology_schema_recommendation.md
docs/agentic_layout/layout_compiler_v1_scope.md
```

The report must answer:

1. What fields should `TopologyPlan` have?
2. Should ports be explicit in topology output?
3. What component catalog metadata is missing?
4. What failures did direct-coordinate output show?
5. What does `LayoutCompiler v1` need to handle?
6. What is explicitly out of scope for `LayoutCompiler v1`?

Expected likely conclusions:

- Add catalog-level `ports[]` metadata eventually.
- Begin with a small motif compiler, not a general layout compiler.
- Support known topologies first:
  - linear pass-through chain
  - two-mirror steering
  - single splitter branch
  - simple lens focus
- Delay arbitrary graph layout and Mach-Zehnder-quality routing until after trace metadata improves.

Acceptance criteria:

- Experiment report is concrete and cites actual planner outputs.
- Topology schema recommendation includes examples.
- Layout compiler scope is small enough to implement next.
- No full layout compiler is implemented in this milestone.

Commit/push:

```bash
git status --short
git add docs/agentic_layout examples/agentic_experiments examples/output src/optiverse/agentic tests/agentic
git commit --no-gpg-sign -m "Document planner experiment findings"
git push
```

## Milestone 7: Final Cleanup And Handoff

Purpose: leave the repo in a state where the next long-running task can implement `TopologyPlan` and `LayoutCompiler v1`.

Tasks:

- Ensure all commands in this plan still work or update docs.
- Ensure generated outputs are either deterministic or clearly marked as examples.
- Ensure no accidental unrelated files are staged.
- Run focused tests:

  ```bash
  .venv313/bin/python -m ruff check src/optiverse/agentic tests/agentic examples/agentic_layout_demo.py
  .venv313/bin/python -m pytest tests/agentic
  .venv313/bin/python examples/agentic_layout_demo.py --output-dir examples/output
  ```

- Optional broader smoke:

  ```bash
  QT_QPA_PLATFORM=offscreen .venv313/bin/python - <<'PY'
  from pathlib import Path
  from PyQt6 import QtWidgets
  from optiverse.ui.views.main_window import MainWindow

  app = QtWidgets.QApplication([])
  window = MainWindow()
  path = Path("examples/output/agentic_hwp_pbs.scene.json").resolve()
  window.file_controller.file_manager.open_file(str(path))
  print("loaded", path)
  window.close()
  app.processEvents()
  PY
  ```

Final deliverables:

- `src/optiverse/agentic/` package.
- `tests/agentic/` tests.
- CLI commands for catalog export, demo run, benchmark run, and planner-output evaluation.
- Constraint-based scorer.
- Validator.
- Benchmark fixtures.
- Prompt templates.
- Experiment report.
- Topology schema recommendation.
- Layout compiler v1 scope.

Final commit/push:

```bash
git status --short
git add plan.md src/optiverse/agentic tests/agentic docs/agentic_layout examples
git commit --no-gpg-sign -m "Finalize agentic layout harness plan and findings"
git push
```

## Out Of Scope For This Plan

Do not implement these unless explicitly re-scoped:

- General arbitrary topology-to-coordinate layout compiler.
- Full port metadata migration across all component JSON files.
- GUI integration beyond opening generated scene JSON.
- Live Thorlabs/vendor catalog fetching.
- Required OpenAI/Anthropic/other LLM dependency.
- Full optical path length through refractive media.
- Complete interaction ledger in the raytracing engine.
- Full mechanical breadboard/hole constraint solver.

## Risk Register

### Risk: LayoutCompiler Becomes The Whole Project

Mitigation: do not build it yet. Use experiments to decide the schema and v1 scope.

### Risk: Current Component Catalog Has No Ports

Mitigation: derive temporary ports from interface geometry for experiments. Recommend explicit `ports[]` metadata only after seeing LLM topology outputs.

### Risk: TraceScorer Is Blind To Branch Semantics

Mitigation: start with `RayPath` scoring but document missing metadata. Do not pretend reflected/transmitted labels are known unless inferred.

### Risk: LLM Output Does Not Match Imagined Schema

Mitigation: make Milestone 5 and 6 schema-discovery milestones. Archive raw outputs and design from observed artifacts.

### Risk: GUI Dependencies Creep Into Headless Code

Mitigation: tests should import `optiverse.agentic` without creating `QApplication`. Keep scene writing as JSON, not `QGraphicsScene`.

### Risk: Generated Outputs Become Noisy

Mitigation: deterministic UUIDs, stable sorting, stable output directories, and concise report JSON.

### Risk: Existing Package Configuration Excludes New Subpackages

Mitigation: deliberately verify imports from editable and, if feasible, wheel-style install. Update package discovery if needed.

## Suggested Final Summary For The Agent

When this plan is complete, summarize:

- What was built.
- Which benchmarks pass.
- What direct-coordinate LLM outputs got wrong.
- What topology/intent outputs looked like.
- What schema should be built next.
- What `LayoutCompiler v1` should and should not do.
- All commits pushed to `origin`.
