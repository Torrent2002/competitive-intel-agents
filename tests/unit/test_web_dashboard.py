from pathlib import Path
from tempfile import TemporaryDirectory

from competitive_intel_agents.models import (
    AnalysisClaim,
    ReportDraft,
    ReviewFeedback,
    RoundEvent,
    RunResult,
    SourceArtifact,
    ToolCall,
)
from competitive_intel_agents.web import (
    render_run_list,
    render_run_detail,
)
from competitive_intel_agents.workspace import LocalWorkspace


def _populate_workspace(workspace: LocalWorkspace, run_id: str = "run_web_001"):
    """Save a complete run into a workspace so the dashboard can render it."""
    workspace.save_run_result(
        RunResult(
            run_id=run_id,
            status="completed",
            report_id="report_w1",
            review_feedback=[
                ReviewFeedback(
                    issue="weak_inference",
                    target_agent="analyst",
                    target_artifact_id="claim_w1",
                    message="Needs more evidence.",
                    required_action="add_evidence",
                )
            ],
        )
    )
    workspace.artifacts.save_source(
        SourceArtifact(
            id="src_w1",
            run_id=run_id,
            url="https://example.com/x",
            title="Competitor Pricing Page",
            snippet="Pricing data from public page.",
        )
    )
    workspace.artifacts.save_claim(
        AnalysisClaim(
            id="claim_w1",
            run_id=run_id,
            text="Competitor dropped price by 10%.",
            source_ids=["src_w1"],
            confidence="high",
            reasoning="Public pricing page comparison.",
        )
    )
    workspace.artifacts.save_report(
        ReportDraft(
            id="report_w1",
            run_id=run_id,
            sections={"Overview": "Price analysis results."},
            claim_ids=["claim_w1"],
            source_ids=["src_w1"],
        )
    )
    journal = workspace.journal
    journal.append(
        RoundEvent(
            id=f"{run_id}:collector:1",
            run_id=run_id,
            agent="collector",
            round=1,
            decision="continue",
            tool_calls=[
                ToolCall(id="tc_1", name="web_search", args={"q": "pricing"})
            ],
            signals=[],
            output_artifact_ids=["src_w1"],
        )
    )
    journal.append(
        RoundEvent(
            id=f"{run_id}:analyst:1",
            run_id=run_id,
            agent="analyst",
            round=1,
            decision="continue",
            output_artifact_ids=["claim_w1"],
        )
    )
    journal.append(
        RoundEvent(
            id=f"{run_id}:reviewer:1",
            run_id=run_id,
            agent="reviewer",
            round=1,
            decision="stop",
            review_feedback=[
                ReviewFeedback(
                    issue="weak_inference",
                    target_agent="analyst",
                    target_artifact_id="claim_w1",
                    message="Needs more evidence.",
                    required_action="add_evidence",
                )
            ],
        )
    )


def test_render_run_list_returns_html():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        _populate_workspace(workspace)

        html = render_run_list(workspace)

        assert "<title>Competitive Intel" in html
        assert "run_web_001" in html
        assert "completed" in html
        assert "report_w1" in html


def test_render_run_list_handles_empty_workspace():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)

        html = render_run_list(workspace)

        assert "<title>Competitive Intel" in html
        assert "0 run(s)" in html


def test_render_run_detail_returns_status():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        _populate_workspace(workspace)

        html = render_run_detail(workspace, "run_web_001")

        assert html is not None
        assert "run_web_001" in html
        assert "completed" in html


def test_render_run_detail_includes_sources():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        _populate_workspace(workspace)

        html = render_run_detail(workspace, "run_web_001")

        assert html is not None
        assert "src_w1" in html
        assert "Competitor Pricing Page" in html
        assert "https://example.com/x" in html


def test_render_run_detail_includes_claims():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        _populate_workspace(workspace)

        html = render_run_detail(workspace, "run_web_001")

        assert html is not None
        assert "claim_w1" in html
        assert "Competitor dropped price by 10%" in html


def test_render_run_detail_includes_report_sections():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        _populate_workspace(workspace)

        html = render_run_detail(workspace, "run_web_001")

        assert html is not None
        assert "Overview" in html
        assert "Price analysis results" in html


def test_render_run_detail_includes_reviewer_feedback():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        _populate_workspace(workspace)

        html = render_run_detail(workspace, "run_web_001")

        assert html is not None
        assert "Reviewer Feedback" in html
        assert "weak_inference" in html


def test_render_run_detail_includes_journal_events():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        _populate_workspace(workspace)

        html = render_run_detail(workspace, "run_web_001")

        assert html is not None
        assert "Journal Events" in html
        assert "collector" in html


def test_render_run_detail_includes_provenance():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        _populate_workspace(workspace)

        html = render_run_detail(workspace, "run_web_001")

        assert html is not None
        assert "Provenance" in html
        assert "Nodes:" in html


def test_render_run_detail_includes_agent_rounds():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        _populate_workspace(workspace)

        html = render_run_detail(workspace, "run_web_001")

        assert html is not None
        assert "Agent Rounds" in html
        assert "collector" in html


def test_render_run_detail_returns_none_for_missing_run():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)

        html = render_run_detail(workspace, "nonexistent_run")

        assert html is None
