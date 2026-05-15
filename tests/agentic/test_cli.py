import io
import json
import sys

import pytest

from optiverse.agentic.cli import main
from optiverse.agentic.schema import demo_goal_spec


def _run_json_command(args, stdin_data, monkeypatch, capsys):
    if stdin_data is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_data)))
    exit_code = main(args)
    captured = capsys.readouterr()
    assert captured.err == ""
    return exit_code, json.loads(captured.out)


@pytest.mark.parametrize(
    "command",
    [
        "demo",
        "catalog",
        "compile",
        "validate",
        "trace",
        "score",
        "render",
        "open",
        "run-benchmark",
        "run-all-benchmarks",
        "export-benchmark-fixtures",
        "make-prompt",
        "evaluate-planner-output",
        "run-llm-benchmark",
    ],
)
def test_subcommand_help_exits_cleanly(command, capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([command, "--help"])

    assert exc_info.value.code == 0
    assert "usage:" in capsys.readouterr().out


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


def test_catalog_cli_defaults_to_stdout(capsys):
    exit_code = main(["catalog"])

    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert any(item["catalog_id"] == "pbs_2in" for item in data)


def test_composable_compile_validate_trace_score_pipeline(tmp_path, monkeypatch, capsys):
    goal_path = tmp_path / "goal.json"
    goal_path.write_text(json.dumps(demo_goal_spec().to_dict()), encoding="utf-8")

    exit_code, compiled = _run_json_command(["compile", str(goal_path)], None, monkeypatch, capsys)
    assert exit_code == 0
    assert compiled["version"] == "2.0"
    assert compiled["_agentic"]["goal"]["goal_id"] == "agentic_hwp_pbs"

    exit_code, validated = _run_json_command(["validate", "-"], compiled, monkeypatch, capsys)
    assert exit_code == 0
    assert validated["_agentic"]["validation"]["passed"] is True

    exit_code, traced = _run_json_command(["trace", "-"], validated, monkeypatch, capsys)
    assert exit_code == 0
    assert traced["_agentic"]["trace"]["path_count"] == 2

    exit_code, score = _run_json_command(["score", "-"], traced, monkeypatch, capsys)
    assert exit_code == 0
    assert score["score"]["passed"] is True


def test_compile_cli_can_write_scene_file(tmp_path):
    goal_path = tmp_path / "goal.json"
    scene_path = tmp_path / "scene.json"
    goal_path.write_text(json.dumps(demo_goal_spec().to_dict()), encoding="utf-8")

    exit_code = main(["compile", str(goal_path), "--output", str(scene_path)])

    assert exit_code == 0
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    assert scene["version"] == "2.0"
    assert scene["_agentic"]["goal"]["goal_id"] == "agentic_hwp_pbs"


def test_render_cli_writes_png(tmp_path, monkeypatch, capsys):
    exit_code, traced = _run_json_command(
        ["trace", "-"], demo_goal_spec().to_dict(), monkeypatch, capsys
    )
    assert exit_code == 0
    output_path = tmp_path / "render.png"

    exit_code, report = _run_json_command(
        ["render", "-", "--output", str(output_path)], traced, monkeypatch, capsys
    )

    assert exit_code == 0
    assert report["rendered"] == str(output_path)
    assert output_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_open_cli_launches_gui_with_scene_path(tmp_path, monkeypatch, capsys):
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(json.dumps({"version": "2.0", "items": []}), encoding="utf-8")
    popen_calls = []

    class FakeProcess:
        pid = 12345

    def fake_popen(command):
        popen_calls.append(command)
        return FakeProcess()

    monkeypatch.setattr("optiverse.agentic.cli.subprocess.Popen", fake_popen)

    exit_code = main(["open", str(scene_path)])

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["opened"] == str(scene_path)
    assert report["pid"] == 12345
    assert popen_calls == [
        [sys.executable, "-m", "optiverse.app.main", str(scene_path.resolve())]
    ]
