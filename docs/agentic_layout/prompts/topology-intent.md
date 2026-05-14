# Topology/Intent Prompt

Use this mode to inspect what topology and artifact-level intent a model naturally emits.

The generated prompt asks for qualitative structure only:

- component sequence or graph
- intended ports or arms if the model wants to name them
- component choices
- artifact-level parameters such as HWP fast-axis angle or lens focal length
- constraints and rationale

Expected response shape is intentionally loose:

```json
{
  "topology": "source -> HWP -> PBS -> two detector arms",
  "components": [
    {"role": "polarization rotator", "catalog_id": "waveplate_hwp"},
    {"role": "polarizing splitter", "catalog_id": "pbs_2in"}
  ],
  "parameters": {
    "HWP1.fast_axis_deg": 22.5
  },
  "constraints": [
    "two output branches",
    "50/50 power split"
  ]
}
```

The current evaluator archives this output and performs only structural checks. It does not compile topology into coordinates yet.
