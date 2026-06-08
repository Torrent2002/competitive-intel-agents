import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "competitive_intel_agents.cli", *args],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_run_prints_human_readable_summary() -> None:
    result = run_cli("run", "--input", "tests/fixtures/request.json")

    assert result.returncode == 0
    assert "Loaded request: tests/fixtures/request.json" in result.stdout
    assert "Run id: run_" in result.stdout
    assert "Run status: approved" in result.stdout
    assert "Sources: 2" in result.stdout
    assert "Claims: 2" in result.stdout
    assert "Report id: report_" in result.stdout


def test_cli_run_rejects_invalid_json(tmp_path: Path) -> None:
    bad_request = tmp_path / "bad-request.json"
    bad_request.write_text("{not json", encoding="utf-8")

    result = run_cli("run", "--input", str(bad_request))

    assert result.returncode != 0
    assert "invalid JSON" in result.stderr


def test_cli_run_accepts_config_and_fake_model_flags() -> None:
    result = run_cli(
        "run",
        "--input",
        "tests/fixtures/request.json",
        "--config",
        "config/agent_profiles.yaml",
        "--fake-model",
    )

    assert result.returncode == 0
    assert "Run status: approved" in result.stdout


def test_cli_run_accepts_real_web_flag_with_workspace_cache(tmp_path: Path) -> None:
    result = run_cli(
        "run",
        "--input",
        "tests/fixtures/request.json",
        "--workspace",
        str(tmp_path / "workspace"),
        "--real-web",
        "--help",
    )

    assert result.returncode == 0
    assert "--real-web" in result.stdout


def test_cli_run_writes_markdown_report(tmp_path: Path) -> None:
    output_path = tmp_path / "report.md"

    result = run_cli(
        "run",
        "--input",
        "tests/fixtures/request.json",
        "--output",
        str(output_path),
    )

    assert result.returncode == 0
    assert f"Wrote report: {output_path}" in result.stdout
    report_text = output_path.read_text(encoding="utf-8")
    assert report_text.startswith("# Competitive Intelligence Report")
    assert "## Overview" in report_text
    assert "## Sources" in report_text


def test_cli_run_persists_workspace_and_show_dashboard(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    result = run_cli(
        "run",
        "--input",
        "tests/fixtures/request.json",
        "--workspace",
        str(workspace),
        "--show-dashboard",
    )

    assert result.returncode == 0
    assert "Run status: approved" in result.stdout
    assert "Run:" in result.stdout
    assert "Status: completed" in result.stdout
    assert "Agent rounds:" in result.stdout
    assert (workspace / "artifacts.sqlite").exists()
    assert (workspace / "journal.sqlite").exists()
    assert (workspace / "runs.json").exists()


def test_cli_dashboard_reads_persisted_run_from_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_result = run_cli(
        "run",
        "--input",
        "tests/fixtures/request.json",
        "--workspace",
        str(workspace),
    )
    run_id = next(
        line.split(": ", 1)[1]
        for line in run_result.stdout.splitlines()
        if line.startswith("Run id:")
    )

    dashboard = run_cli(
        "dashboard",
        "--run-id",
        run_id,
        "--workspace",
        str(workspace),
    )

    assert dashboard.returncode == 0
    assert f"Run: {run_id}" in dashboard.stdout
    assert "Status: completed" in dashboard.stdout
    assert "Sources: 2" in dashboard.stdout
    assert "Claims: 2" in dashboard.stdout


def test_cli_runs_lists_persisted_runs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_cli("run", "--input", "tests/fixtures/request.json", "--workspace", str(workspace))

    result = run_cli("runs", "--workspace", str(workspace))

    assert result.returncode == 0
    assert "Run id" in result.stdout
    assert "approved" in result.stdout


def test_cli_chat_runs_pipeline_and_accepts_inspection_commands(tmp_path: Path) -> None:
    output_path = tmp_path / "chat-report.md"
    user_input = "\n".join(
        [
            "Notion",
            "productivity",
            "Coda, Airtable",
            "pricing, collaboration features",
            "dashboard",
            "sources",
            "claims",
            "report",
            f"save {output_path}",
            "exit",
            "",
        ]
    )

    result = subprocess.run(
        [sys.executable, "-m", "competitive_intel_agents.cli", "chat"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        input=user_input,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Competitive Intel interactive session" in result.stdout
    assert "Run status: approved" in result.stdout
    assert "Status: completed" in result.stdout
    assert "source_" in result.stdout
    assert "claim_" in result.stdout
    assert "## Overview" in result.stdout
    assert f"Wrote report: {output_path}" in result.stdout
    assert output_path.exists()


def test_cli_dashboard_missing_run_is_readable(tmp_path: Path) -> None:
    result = run_cli(
        "dashboard",
        "--run-id",
        "missing_run",
        "--workspace",
        str(tmp_path / "workspace"),
    )

    assert result.returncode != 0
    assert "run not found: missing_run" in result.stderr


def test_request_fixture_is_valid_json() -> None:
    payload = json.loads(
        (PROJECT_ROOT / "tests" / "fixtures" / "request.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["company"]
