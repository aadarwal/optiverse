# TopologyPlan Recommendation

Purpose: capture the artifact an LLM can reliably produce before deterministic layout.

## Recommended Shape

```json
{
  "topology_id": "hwp_pbs_splitter",
  "source": {
    "wavelength_nm": 780,
    "polarization": "horizontal",
    "ray_bundle": "single"
  },
  "components": [
    {
      "label": "HWP1",
      "catalog_id": "waveplate_hwp",
      "role": "rotate linear polarization for 50/50 PBS split",
      "parameters": {
        "fast_axis_deg": 22.5
      }
    },
    {
      "label": "PBS1",
      "catalog_id": "pbs_2in",
      "role": "split horizontal and vertical polarization"
    }
  ],
  "edges": [
    {"from": "source", "to": "HWP1"},
    {"from": "HWP1", "to": "PBS1"},
    {"from": "PBS1", "to": "D1", "branch": "transmitted"},
    {"from": "PBS1", "to": "D2", "branch": "reflected"}
  ],
  "constraints": [
    {"kind": "branch_count", "params": {"expected": 2}},
    {"kind": "power_at_target", "params": {"target": "D1", "expected_power_fraction": 0.5}},
    {"kind": "polarization_at_target", "params": {"target": "D2", "polarization": "vertical"}}
  ],
  "layout_hints": {
    "motif": "single_splitter",
    "style": "compact_right_angle"
  }
}
```

## Field Notes

- `components[].catalog_id` must refer to the catalog summary.
- `components[].parameters` should hold artifact-level optics values, not coordinates.
- `edges[]` may include branch names when the model knows them, but branch labels are advisory until the raytracer has richer interaction metadata.
- `constraints[]` should reuse the scorer constraint kinds where possible.
- `layout_hints.motif` should be a small enum, not a free-form layout request.

## Ports

Ports should not be required from the LLM in the first schema. The model can mention them if useful, but deterministic code should derive v1 ports from interface geometry.

Add explicit catalog-level `ports[]` later with:

- port label
- local position
- nominal input/output direction
- compatible element/interface index
- branch identity for splitters where known

This should happen after the motif compiler proves which port facts it actually needs.
