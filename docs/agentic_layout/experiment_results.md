# Agentic Layout Experiment Results

Date: May 14, 2026

Planner-output source: Codex GPT-5 coding agent manual path. No external provider credentials were used for this run.

Reports:

```text
examples/output/experiments/summary.json
examples/output/experiments/{benchmark}/{mode}/report.json
```

Saved planner outputs:

```text
examples/agentic_experiments/{benchmark}/{mode}/model_output.json
```

## Matrix

| Benchmark | Direct Placement | Topology/Intent |
| --- | --- | --- |
| `hwp_pbs_splitter` | passed | archived, structurally valid |
| `two_mirror_steering` | failed at score | archived, structurally valid |
| `single_lens_focus` | passed | archived, structurally valid |
| `four_f_telescope` | failed at score | archived, structurally valid |
| `mach_zehnder_skeleton` | passed | archived, structurally valid |

Topology/intent mode is not compiled yet. A pass there means the JSON was archived and had topology-like structure; it does not mean Optiverse can place it.

## Failure Evidence

`two_mirror_steering/direct-placement` failed despite passing validation. The planner used intended mirror hit points as component origins. In Optiverse, the mirror interface is offset from the sprite origin, so the beam missed both mirrors. The scored path had no `path_element_ids`, missed `D_corner` by 100 mm, and failed the expected `M1 -> M2` topology check.

`four_f_telescope/direct-placement` also passed validation but failed scoring. The planner placed the second lens one focal length after the first lens instead of `f1 + f2`. Rays hit both lenses and the centroid stayed on-axis, but the output spot RMS at the scoring plane was 10 mm instead of the expected 4 mm.

## Interpretation

The criticism that `LayoutCompiler` is the main project is supported. Direct coordinate emission is brittle even when component choices and high-level physics are correct. The model-style outputs got textbook decisions right, but failed on:

- component origin versus optical interface origin
- mirror fold geometry
- lens-spacing semantics
- scoring details that require ray intersections rather than prose reasoning

The topology outputs were more useful as schema-discovery artifacts. They consistently expressed roles, component choices, and artifact-level parameters without pretending to own coordinates.

## Recommendation

Build `TopologyPlan` around:

- component roles and catalog IDs
- ordered optical graph/arms
- artifact-level parameters such as `fast_axis_deg`, `efl_mm`, split ratio, and required lens spacing
- named constraints and intended detector/plane checks

Then build the first `LayoutCompiler` around a small deterministic grammar:

- place straight chains by interface midpoint, not sprite origin
- add a mirror-fold primitive with explicit incoming/outgoing directions
- add a lens-chain primitive that understands focal spacing
- keep using the raytracer and constraint scorer as the judge

Do not treat LLM direct coordinates as the product architecture. Keep direct placement as a baseline/failure mode.
