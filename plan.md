# Optiverse Agentic CLI & Plugin Plan

## Completion Target

Build the composable agentic command surface and the two consumers on top of it, so that a natural-language optical-experiment request becomes a verified, GUI-viewable layout. On completion the repository has:

1. A composable `optiverse-agent` CLI: each pipeline step is its own subcommand with structured JSON I/O.
2. A mini-LayoutCompiler that translates planner-friendly hit-point coordinates into Optiverse component origins, plus focal-length-based spacing.
3. Natural-language goal parsing (`parse-goal`) behind a swappable, mockable LLM provider.
4. A thin `design` orchestrator: NL goal → plan → compile → validate → trace → score → minimal iterate → auto-open GUI.
5. A Claude Code plugin (skill) that teaches a coding agent to drive the same CLI.

This is **not** a numerical optimizer, an MCP server, or a general topology-graph layout compiler. See "Out Of Scope".

## Core Thesis

- The durable asset is the **composable CLI command surface**. The planner is a swappable *consumer* of it.
- Two consumers ship in this plan: the `design` command (Anthropic, autonomous, CI-testable) and Claude Code via the plugin skill. Both call the same subcommands.
- The iteration loop belongs to the planner. In the plugin path it is free — it is the coding agent's native loop. So the `design` command's loop is deliberately minimal (cap 3 rounds); do not over-build it.
- The mini-LayoutCompiler lives inside the `compile` command, so every planner benefits without re-deriving Optiverse coordinate conventions.
- Plugin-readiness is an architectural constraint on every milestone, not a final feature: structured JSON I/O, deterministic behavior, documented commands, no hidden state.

## Execution Contract

This plan is executed by a long-running agent. Follow these rules exactly.

- **Branches:** Work only on `feature/**` branches. CI triggers on push to `feature/**`; other branch names do not trigger CI. Suggested names: `feature/agentic-cli-m1-commands`, `feature/agentic-cli-m2-layout`, etc.
- **One PR per milestone.** Each milestone is a separate feature branch cut from the latest `main`, and a separate pull request into `main` of the fork (`origin`, `aadarwal/optiverse`).
- **Never commit directly to `main`.** Never push to `upstream` (`QPG-MIT/optiverse`).
- **Merge only on green CI.** After pushing a milestone branch and opening its PR, wait for the CI run (Ubuntu/macOS/Windows, Python 3.10). Merge the PR only when CI concludes `success`. If CI fails, fix on the same branch, push, re-check; do not merge red.
- **CI is the source of truth.** Run `ruff`, `mypy`, and `pytest` locally before pushing, but local mypy (Python 3.13) differs from CI mypy (Python 3.10) because of numpy stub versions. A local pass does not guarantee a CI pass.
- **Stage only intended files.** Inspect `git status --short` before staging. Do not stage `test.json` / `test2.json` at the repo root — they are unrelated artifacts.
- **Signing:** If commit signing blocks on GPG/SSH, use `git commit --no-gpg-sign` and note it. Do not skip other hooks.
- **Environment:** Use `.venv313/bin/python`.

Per-milestone shipping sequence:

```bash
git switch main && git pull origin main
git switch -c feature/agentic-cli-mN-<topic>
# ... implement milestone ...
.venv313/bin/python -m ruff check src tests
.venv313/bin/python -m mypy src/
.venv313/bin/python -m pytest tests/agentic tests/raytracing tests/core tests/integration
git add <intended files>
git commit -m "<message>"
git push -u origin feature/agentic-cli-mN-<topic>
gh pr create --repo aadarwal/optiverse --base main --head feature/agentic-cli-mN-<topic> \
  --title "<title>" --body "<summary + test plan>"
# wait for CI, then:
gh run watch <run-id> --repo aadarwal/optiverse --exit-status
gh pr merge <pr-number> --repo aadarwal/optiverse --merge
```

## Repository Starting Point

- `main` of the fork is at the merge of PR #1; the `optiverse.agentic` package already exists with: `catalog`, `schema`, `compiler`, `scene_writer`, `scorer`, `validator`, `benchmarks`, `experiments`, `llm_client`, `cli`.
- The raytracer exposes `RayPath.path_element_ids` (path-element ledger).
- 5 benchmarks exist under `examples/agentic_benchmarks/`. `two_mirror_steering` and `four_f_telescope` are the layouts that fail planner direct-placement; M2 targets them.
- CI is proven working on the fork (ruff + mypy + pytest, 3-OS matrix).

## Milestone 1: Composable Command Surface

Purpose: turn the agentic CLI into a clean, plugin-ready set of single-purpose subcommands with structured JSON I/O. This is the durable core both consumers depend on.

Build:

- A `optiverse-agent` console entry point in `pyproject.toml` (`[project.scripts]`).
- Subcommands, each doing one thing, each reading/writing structured JSON (stdout by default, `--output PATH` to write a file), each with a documented `--help`:
  - `catalog` — components with physics annotations (exists; ensure clean JSON).
  - `compile` — placements JSON → Optiverse scene JSON (wraps `compiler`; M2 extends it).
  - `validate` — scene/plan JSON → validation report JSON (wraps `validator`).
  - `trace` — scene JSON → ray-path + results JSON (wraps the raytracer).
  - `score` — scene JSON + goal JSON → constraint report JSON (wraps `scorer`).
  - `render` — scene JSON → PNG schematic (headless, so an agent can see a layout).
  - `open` — scene JSON → launch the Optiverse GUI.
- Consistent exit codes: `0` success, non-zero failure.
- Keep existing commands (`demo`, `run-benchmark`, etc.) working; refactor them to compose the new subcommands where reasonable.

Acceptance criteria:

- `optiverse-agent <cmd> --help` works for every subcommand and documents its JSON I/O.
- Commands compose: `optiverse-agent compile p.json | optiverse-agent validate - | optiverse-agent trace -` works via stdin/stdout.
- `render` produces a PNG; `open` launches the GUI on a scene file.
- Unit tests cover every subcommand.
- ruff + mypy clean; CI green on the PR.

PR title: "Composable agentic CLI command surface".

## Milestone 2: mini-LayoutCompiler

Purpose: fix the failure the planner experiment identified — planners place components by where the beam should hit them, but Optiverse stores components by origin, and those points differ.

Build, inside the `compile` command:

- Accept placements in an **anchor form**: a component may be specified by the scene point where its optical interface should sit, plus orientation — not only by origin.
- Translate anchor → Optiverse origin using each component's interface offset derived from catalog geometry.
- Focal-length-aware spacing: when a plan declares a relay/telescope relationship, derive component separation from catalog focal lengths rather than trusting raw coordinates.
- Keep origin-form placement supported (backward compatible).

Acceptance criteria:

- `two_mirror_steering` and `four_f_telescope` benchmarks pass when expressed with anchor-form placements.
- Unit tests for the anchor→origin translation and focal-length spacing math.
- Existing benchmarks still pass.
- CI green on the PR.

PR title: "Add mini-LayoutCompiler: hit-point anchoring and focal-length spacing".

## Milestone 3: NL Goal Parsing And Provider Abstraction

Purpose: turn natural language into the constraint `GoalSpec`; make the LLM provider swappable and mockable for CI.

Build:

- Extend `llm_client.py` into a provider abstraction: an `anthropic` provider and a `mock`/`recorded` provider that returns fixed responses for deterministic tests.
- A `parse-goal` subcommand: natural-language string → `GoalSpec` JSON (constraints such as `target_hit`, `power_at_target`, `polarization_at_target`).
- Versioned prompt templates under `docs/agentic_layout/prompts/`.

Acceptance criteria:

- `optiverse-agent parse-goal "50/50 split a 780 nm beam to two detectors" --provider mock` returns a valid `GoalSpec` JSON deterministically.
- The `anthropic` provider works when `ANTHROPIC_API_KEY` is set; absence of a key fails cleanly, never hangs.
- No required network dependency for the test suite (CI uses `mock`).
- CI green on the PR.

PR title: "Add NL-goal parsing and swappable LLM provider".

## Milestone 4: `design` Orchestrator

Purpose: the thin autonomous path — and the CI-testable end-to-end regression harness.

Build:

- A `design` subcommand chaining: NL goal → `parse-goal` → provider plans placements → `compile` → `validate` → `trace` → `score`. On failure, feed the score report back to the provider and retry, capped at 3 rounds. On success, auto-launch the GUI via `open`.
- The loop is intentionally minimal — it is a fallback and test path, not the premium UX.
- Flags: `--provider`, `--no-open` (headless/CI), `--max-rounds`.
- A `mock`/recorded-provider path so the full pipeline runs deterministically in CI.

Acceptance criteria:

- `optiverse-agent design "<known goal>" --provider mock --no-open` runs the whole pipeline deterministically and exits `0` on a known-good goal.
- With a real provider it produces a scene and opens the GUI.
- The minimal iterate loop is exercised by a test where round 1 fails and a later round passes.
- CI green on the PR.

PR title: "Add design orchestrator with minimal iteration loop and GUI hand-off".

## Milestone 5: Claude Code Plugin Skill

Purpose: the premium path — a coding agent as the planner, driving the same CLI.

Build:

- A Claude Code plugin directory containing a **skill** (markdown) that teaches a coding agent the Optiverse design workflow: how to call `optiverse-agent catalog/compile/validate/trace/score/render/open`, how to read score reports, how to iterate, and when to call `open`.
- A plugin manifest and an install README.
- The skill must rely only on the composable CLI — no new intelligence in Optiverse.

Acceptance criteria:

- The plugin installs into Claude Code.
- Documented manual smoke test: install the plugin, ask the coding agent to design the HWP/PBS splitter, confirm it drives the CLI and opens the GUI.
- Because this milestone needs the Claude Code runtime, verification is partly manual; the PR documents the exact smoke steps and expected output.
- CI green on the PR (CI covers the non-runtime parts).

PR title: "Add Claude Code plugin skill for agentic optical design".

## Milestone 6: Documentation And Handoff

Purpose: leave the system usable and documented.

Build:

- End-user docs: using the `optiverse-agent` CLI, and installing/using the plugin.
- Update `README.md` and `CHANGELOG.md`.
- A final `docs/agentic_layout/cli_and_plugin.md` describing the command surface and the two consumers.
- Final verification: every command in this plan runs; benchmarks pass; CI green.

Acceptance criteria:

- Docs are accurate and every documented command works.
- CI green on the PR.

PR title: "Document agentic CLI and plugin".

## Out Of Scope

Do not implement these unless explicitly re-scoped:

- Numerical refiner / position-angle optimizer.
- MCP server (the plugin is skill-based first).
- Wave-optics, interference, or optical-path-length constraints.
- A general topology-graph layout compiler (only the mini-LayoutCompiler's two rules).
- Vendor (Thorlabs/Edmund) catalog integration.
- Any change pushed to `upstream` (`QPG-MIT/optiverse`).

## Risk Register

- **Local mypy ≠ CI mypy.** numpy stub versions differ between Python 3.13 (local) and 3.10 (CI). Always confirm against CI; never merge before CI is green.
- **Branch naming.** Only `feature/**` pushes trigger CI. A wrong prefix means no CI runs and a silently unverified merge.
- **GUI auto-open needs a display.** All CI tests must use `--no-open`. Never call `open` in an automated test.
- **LLM non-determinism.** Every CI test uses the `mock`/recorded provider. Real-provider behavior is verified manually only.
- **M5 needs the Claude Code runtime.** Its verification is partly manual; document the smoke steps in the PR.
- **`design` loop scope creep.** Keep it capped at 3 rounds and minimal — the real loop is the coding agent's job in the plugin path.
- **Monolith risk.** Do not fuse the pipeline into one command. `design` must call the composable subcommands, not reimplement them.

## Suggested Final Summary For The Agent

When this plan is complete, summarize:

- The composable command surface and what each subcommand does.
- That the mini-LayoutCompiler flipped `two_mirror_steering` and `four_f_telescope` to passing.
- How the `design` command and the Claude Code plugin both consume the same CLI.
- Which milestones merged via PR with green CI, and their PR numbers.
- Any manual-only verification (M5) and its result.
- Confirmation that nothing was pushed to `upstream`.
