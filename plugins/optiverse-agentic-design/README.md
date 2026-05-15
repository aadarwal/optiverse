# Optiverse Agentic Design Plugin

This plugin packages one skill, `optiverse-design`, for agents that need to design and verify Optiverse optical layouts through the composable `optiverse-agent` CLI.

## Prerequisites

From the Optiverse repository root:

```bash
.venv313/bin/python -m pip install -e .
.venv313/bin/optiverse-agent --help
```

## Claude Code Local Install Smoke

This repository includes a local Claude Code marketplace at `.claude-plugin/marketplace.json`. From the repository root, install it into local scope:

```bash
claude plugin marketplace add ./ --scope local
claude plugin install optiverse-agentic-design@optiverse-local --scope local
```

In an already-running interactive Claude Code session, run `/reload-plugins` after installation.

Then ask:

```text
/optiverse-agentic-design:optiverse-design Design a HWP/PBS splitter in Optiverse, verify it with the CLI, render it, and open the GUI when it passes.
```

Expected behavior:

- The agent runs `optiverse-agent catalog` or `optiverse-agent design`.
- The agent writes artifacts under an output directory such as `examples/output/agentic_runs/...`.
- The agent verifies the score report has `"passed": true`.
- The agent renders a PNG schematic.
- The agent calls `optiverse-agent open <scene.json>` only after the score passes.

## Headless Smoke

Run this without Claude Code to verify the same CLI path that the skill teaches:

```bash
RUN_DIR=/tmp/optiverse-plugin-smoke
rm -rf "$RUN_DIR"
.venv313/bin/optiverse-agent design \
  "50/50 split a 780 nm horizontally polarized beam with a HWP and PBS" \
  --provider mock \
  --no-open \
  --output-dir "$RUN_DIR" \
  --output "$RUN_DIR/design.report.json"
.venv313/bin/python - <<'PY'
import json
from pathlib import Path
report = json.loads(Path("/tmp/optiverse-plugin-smoke/design.report.json").read_text())
assert report["passed"] is True
assert Path("/tmp/optiverse-plugin-smoke/design.scene.json").is_file()
assert Path("/tmp/optiverse-plugin-smoke/design.png").is_file()
PY
```

Runtime plugin verification is intentionally manual because it depends on an installed Claude Code environment. The headless smoke confirms that the Optiverse side of the workflow is available.
