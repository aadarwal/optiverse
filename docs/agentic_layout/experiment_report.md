# Planner Experiment Report

Date: May 14, 2026

Source: manual saved-output path using Codex GPT-5 coding-agent outputs generated during this implementation run. No external provider credentials were used.

Primary artifacts:

- `examples/agentic_experiments/{benchmark}/{mode}/model_output.json`
- `examples/output/experiments/{benchmark}/{mode}/report.json`
- `examples/output/experiments/summary.json`

## Results

| Benchmark | Direct Placement | Topology/Intent |
| --- | --- | --- |
| `hwp_pbs_splitter` | passed | archived, structurally valid |
| `two_mirror_steering` | failed at score | archived, structurally valid |
| `single_lens_focus` | passed | archived, structurally valid |
| `four_f_telescope` | failed at score | archived, structurally valid |
| `mach_zehnder_skeleton` | passed | archived, structurally valid |

Topology/intent mode is archive-only in this scaffold. It is useful for schema discovery, not a claim that coordinates can already be compiled.

## Direct-Coordinate Failures

`two_mirror_steering/direct-placement` passed schema and validation, but score failed:

- target miss distance: 100 mm
- traced path element IDs: `[]`
- failed topology constraint: expected `M1:iface0 -> M2:iface0`

The planner used the desired optical hit points as sprite origins. The actual mirror interface in the catalog is offset from the component origin, so the beam missed both mirrors. This is a direct example of why LLM-emitted coordinates are brittle.

`four_f_telescope/direct-placement` also passed validation, but score failed:

- both paths through `L1:iface0` and `L2:iface0` were present
- centroid at the output plane remained correct
- spot RMS radius was 10 mm, expected 4 mm

The planner placed the second lens one focal length after the first, not `f1 + f2`. This is a physics/layout semantic failure rather than a catalog-selection failure.

## Answers

1. `TopologyPlan` should include benchmark goal, component roles, catalog IDs, graph edges/arms, artifact parameters, and constraints. It should not include final coordinates.
2. Ports should be optional in v1 topology output, but the compiler needs an internal port/interface model immediately. Catalog-level `ports[]` metadata should be added later.
3. Missing catalog metadata: explicit ports, component footprint dimensions separate from image height, optical-axis conventions, preferred input/output directions, and branch labels for splitters.
4. Direct-coordinate output failed on sprite-origin versus optical-interface origin and on lens-spacing semantics.
5. `LayoutCompiler v1` must handle straight chains, mirror folds, single splitters, and simple lens-spacing motifs.
6. Out of scope: arbitrary graph layout, Mach-Zehnder-grade recombination, optical path length through refractive media, mechanical breadboard hole solving, and full transmitted/reflected branch labels.

## Recommendation

Proceed with a small motif-based layout compiler. Keep the LLM focused on topology, roles, constraints, and artifact parameters. Let deterministic code own component coordinates, interface-midpoint placement, mirror fold geometry, and lens spacing. Use the raytracer/scorer as the judge.
