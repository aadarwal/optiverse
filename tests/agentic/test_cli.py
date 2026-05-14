import json

from optiverse.agentic.cli import main


def test_demo_cli_writes_outputs(tmp_path):
    exit_code = main(["demo", "--output-dir", str(tmp_path)])

    assert exit_code == 0
    report_path = tmp_path / "agentic_hwp_pbs.report.json"
    scene_path = tmp_path / "agentic_hwp_pbs.scene.json"
    catalog_path = tmp_path / "agentic_hwp_pbs.catalog.json"
    assert report_path.exists()
    assert scene_path.exists()
    assert catalog_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["score"]["passed"] is True


def test_catalog_cli_writes_summary(tmp_path):
    output_path = tmp_path / "catalog.json"

    exit_code = main(["catalog", "--output", str(output_path)])

    assert exit_code == 0
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert any(item["catalog_id"] == "pbs_2in" for item in data)
