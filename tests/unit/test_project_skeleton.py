import importlib
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_package_and_top_level_modules_import() -> None:
    modules = [
        "competitive_intel_agents",
        "competitive_intel_agents.agents",
        "competitive_intel_agents.artifacts",
        "competitive_intel_agents.cli",
        "competitive_intel_agents.dashboard",
        "competitive_intel_agents.golden",
        "competitive_intel_agents.harness",
        "competitive_intel_agents.journal",
        "competitive_intel_agents.orchestrator",
        "competitive_intel_agents.prompts",
        "competitive_intel_agents.rework",
        "competitive_intel_agents.runtime",
        "competitive_intel_agents.workspace",
    ]

    for module in modules:
        importlib.import_module(module)


def test_agent_profiles_config_exists() -> None:
    config_path = PROJECT_ROOT / "config" / "agent_profiles.yaml"

    assert config_path.exists()
    assert config_path.read_text(encoding="utf-8").strip()


def test_request_fixture_exists_and_is_valid_json() -> None:
    fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "request.json"

    import json

    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert payload["company"]
    assert "market" in payload
    assert isinstance(payload.get("competitors", []), list)
    assert isinstance(payload.get("questions", []), list)


def test_cli_entrypoint_is_registered() -> None:
    pyproject_text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "[project.scripts]" in pyproject_text
    assert 'competitive-intel = "competitive_intel_agents.cli:main"' in pyproject_text


def test_cli_module_runs_with_fixture() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "competitive_intel_agents.cli",
            "run",
            "--input",
            "tests/fixtures/request.json",
        ],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Loaded request:" in result.stdout
    assert "Run status: approved" in result.stdout
