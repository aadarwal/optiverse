# Direct Placement Prompt

Use this mode to test the baseline where the model emits exact component coordinates.

The generated prompt includes:

- benchmark goal JSON without the known answer placements
- target and constraint definitions
- catalog summaries with inferred capabilities

Expected response shape:

```json
{
  "placements": [
    {
      "label": "HWP1",
      "catalog_id": "waveplate_hwp",
      "x_mm": 60.0,
      "y_mm": 0.0,
      "angle_deg": 0.0,
      "interface_overrides": {
        "0": {
          "fast_axis_deg": 22.5
        }
      }
    }
  ]
}
```

The evaluator treats this as executable input: it validates catalog IDs, overrides, geometry, traces rays, and scores benchmark constraints.
