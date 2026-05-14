# LayoutCompiler V1 Scope

`LayoutCompiler` is the main hard problem. V1 should be deliberately small and motif-based.

## Inputs

- `TopologyPlan` with component labels, catalog IDs, roles, parameters, edges, and constraints.
- built-in catalog summary with inferred capabilities.
- optional layout hints such as motif and compactness.

## Outputs

- explicit `Placement` objects
- deterministic scene JSON
- validation report
- trace/scoring report

## Supported Motifs

1. Linear pass-through chain
   - source, waveplates, polarizers, lenses, detectors or target planes
   - place by optical interface midpoint, not sprite origin

2. Two-mirror steering
   - route an incoming beam around one right-angle corner
   - infer mirror centers from intended hit points
   - compute mirror angles from incoming and outgoing directions

3. Single splitter branch
   - one beamsplitter or PBS
   - two orthogonal output arms
   - simple target placement along each branch

4. Simple lens focus and 4f spacing
   - place lenses by focal-length-derived spacing
   - support `f`, `f1 + f2`, and focal-plane target constraints

## Required Internals

- component footprint estimator
- interface midpoint placement helper
- direction propagation for line, mirror, lens, and splitter motifs
- branch grammar for one splitter
- collision/table bounds validator reuse
- grid snapping only after continuous geometry is valid

## Out Of Scope

- arbitrary graph routing
- arbitrary collision backtracking
- full Mach-Zehnder recombination and phase scoring
- optical path length through media
- breadboard hole constraints
- vendor-specific mechanical mount selection
- GUI editing workflows

## First Implementation Slice

Start with `TopologyPlan -> Placement[]` for:

```text
source -> HWP -> PBS -> two targets
source -> M1 -> M2 -> target
source bundle -> L1 -> focal plane
source bundle -> L1 -> L2 -> output plane
```

Every compiler output must immediately run through:

```text
validate_goal -> compile_elements -> trace_rays_polymorphic -> score_paths
```

The compiler should be considered correct only when the scorer passes, not when the generated coordinates look plausible.
