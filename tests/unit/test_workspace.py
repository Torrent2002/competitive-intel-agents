from pathlib import Path

from competitive_intel_agents.models import ReportDraft, RunResult
from competitive_intel_agents.workspace import LocalWorkspace


def test_workspace_persists_run_results(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path / "workspace")
    workspace.save_run_result(RunResult(run_id="run_001", status="approved"))

    reopened = LocalWorkspace(tmp_path / "workspace")

    assert reopened.get_run_result("run_001").status == "approved"
    assert [result.run_id for result in reopened.list_run_results()] == ["run_001"]
    assert (tmp_path / "workspace" / "runs.json").exists()


def test_workspace_exposes_sqlite_stores_across_instances(tmp_path: Path) -> None:
    first = LocalWorkspace(tmp_path / "workspace")
    first.artifacts.save_report(
        ReportDraft(
            id="report_001",
            run_id="run_001",
            sections={"Overview": "Summary."},
        )
    )

    second = LocalWorkspace(tmp_path / "workspace")

    assert second.artifacts.get_latest_report("run_001").id == "report_001"
