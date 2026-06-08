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


def test_request_fixture_is_valid_json() -> None:
    payload = json.loads(
        (PROJECT_ROOT / "tests" / "fixtures" / "request.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["company"]
