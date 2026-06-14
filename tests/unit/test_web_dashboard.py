from pathlib import Path
from tempfile import TemporaryDirectory
from http.client import HTTPConnection
from threading import Thread

from competitive_intel_agents.web import WebDashboardHandler
from http.server import HTTPServer

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
    create_run_from_form,
    render_run_list,
    render_run_detail,
    render_workflow_map,
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
            metadata={
                "content_ref": "file:/tmp/source.txt",
                "char_count": 4096,
            },
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
        assert "Run Analysis" in html
        assert "name=\"company\"" in html
        assert 'href="/workflow"' in html


def test_render_workflow_map_shows_agent_and_rework_paths():
    html = render_workflow_map()

    assert "<title>Agent Workflow Map" in html
    for label in (
        "User Request",
        "Orchestrator",
        "Collector",
        "Analyst",
        "Writer",
        "Reviewer",
        "Report / Final Status",
    ):
        assert label in html
    assert "Reviewer → Collector" in html
    assert "Reviewer → Analyst" in html
    assert "Reviewer → Writer" in html
    assert "needs_more_evidence" in html
    assert "rework_failed" in html
    assert "approved" in html
    assert "approved_with_caveats" in html
    assert "Agent Contract" in html
    assert "collector → analyst → writer → reviewer" in html
    assert "approved means the report passed every reviewer check" in html


def test_render_run_list_handles_empty_workspace():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)

        html = render_run_list(workspace)

        assert "<title>Competitive Intel" in html
        assert "0 run(s)" in html
        assert "Run Analysis" in html


def test_create_run_from_form_persists_request_and_result():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)

        result = create_run_from_form(
            workspace,
            {
                "company": ["Notion"],
                "market": ["productivity"],
                "competitors": ["Coda, Airtable"],
                "questions": ["pricing, collaboration"],
            },
        )

        assert result.status == "rework_failed"
        assert workspace.get_run_result(result.run_id) is not None
        assert workspace.artifacts.get_latest_report(result.run_id) is not None


def test_web_handler_accepts_run_form_post():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        WebDashboardHandler.workspace = workspace
        server = HTTPServer(("127.0.0.1", 0), WebDashboardHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = "company=Notion&market=productivity&competitors=Coda&questions=pricing"
            conn = HTTPConnection("127.0.0.1", server.server_port)
            conn.request(
                "POST",
                "/runs",
                body=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response = conn.getresponse()
            response.read()
        finally:
            server.shutdown()
            thread.join(timeout=2)

        assert response.status == 303
        assert response.getheader("Location", "").startswith("/runs/run_")
        assert len(workspace.list_run_results()) == 1


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
        assert "file:/tmp/source.txt" in html
        assert "4096 chars" in html


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


def test_render_run_detail_includes_agent_workflow_cards():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        _populate_workspace(workspace)

        html = render_run_detail(workspace, "run_web_001")

        assert html is not None
        assert "Agent Workflow" in html
        for agent in ("collector", "analyst", "writer", "reviewer"):
            assert f"agent-card {agent}" in html
        assert "agent-status done" in html
        assert 'href="/workflow"' in html


def test_web_handler_serves_workflow_map():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        WebDashboardHandler.workspace = workspace
        server = HTTPServer(("127.0.0.1", 0), WebDashboardHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = HTTPConnection("127.0.0.1", server.server_port)
            conn.request("GET", "/workflow")
            response = conn.getresponse()
            body = response.read().decode("utf-8")
        finally:
            server.shutdown()
            thread.join(timeout=2)

        assert response.status == 200
        assert "Agent Workflow Map" in body
        assert "Reviewer → Collector" in body


def test_running_run_detail_marks_next_agent_running_and_refreshes():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        run_id = "run_running_001"
        workspace.save_run_result(RunResult(run_id=run_id, status="running"))
        workspace.journal.append(
            RoundEvent(
                id=f"{run_id}:collector:1",
                run_id=run_id,
                agent="collector",
                round=1,
                decision="stop",
            )
        )

        html = render_run_detail(workspace, run_id)

        assert html is not None
        assert '<meta http-equiv="refresh" content="2">' in html
        assert "agent-card analyst is-running" in html
        assert "thinking-dots" in html
        assert "agent-status pending" in html


def test_running_run_detail_explains_agent_without_first_round_event():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        run_id = "run_running_analyst_001"
        workspace.save_run_result(RunResult(run_id=run_id, status="running"))
        workspace.journal.append(
            RoundEvent(
                id=f"{run_id}:collector:1",
                run_id=run_id,
                agent="collector",
                round=1,
                decision="stop",
            )
        )

        html = render_run_detail(workspace, run_id)

        assert html is not None
        assert "Active agent: Analyst" in html
        assert "waiting for its first round event" in html
        assert "Last completed event: collector stop" in html


def test_aborted_run_detail_marks_unreached_agents_blocked():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        run_id = "run_aborted_001"
        workspace.save_run_result(RunResult(run_id=run_id, status="aborted"))
        workspace.journal.append(
            RoundEvent(
                id=f"{run_id}:collector:1",
                run_id=run_id,
                agent="collector",
                round=1,
                decision="abort",
                signals=["max_retries_exceeded"],
            )
        )

        html = render_run_detail(workspace, run_id)

        assert html is not None
        assert "agent-card collector is-aborted" in html
        assert "agent-card analyst is-blocked" in html
        assert "agent-card writer is-blocked" in html
        assert "agent-card reviewer is-blocked" in html
        assert "No report was produced because the run ended before writer." in html


def test_needs_more_evidence_run_marks_collector_for_rework():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        run_id = "run_evidence_001"
        feedback = ReviewFeedback(
            issue="missing_source",
            target_agent="collector",
            target_artifact_id="question_coverage:pricing",
            message="Missing pricing evidence.",
            required_action="Collect pricing evidence.",
        )
        workspace.save_run_result(
            RunResult(
                run_id=run_id,
                status="needs_more_evidence",
                review_feedback=[feedback],
                error="max_rework_attempts_exceeded",
            )
        )
        workspace.journal.append(
            RoundEvent(
                id=f"{run_id}:reviewer:1",
                run_id=run_id,
                agent="reviewer",
                round=1,
                decision="rework",
                review_feedback=[feedback],
            )
        )

        html = render_run_detail(workspace, run_id)

        assert html is not None
        assert "needs_more_evidence" in html
        assert "agent-card collector is-rework" in html
        assert "agent-card analyst is-blocked" in html


def test_run_detail_explains_reviewer_feedback_flow():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        run_id = "run_feedback_flow_001"
        feedback = ReviewFeedback(
            issue="missing_source",
            target_agent="collector",
            target_artifact_id="collector_coverage:Coda",
            message="No active source covers competitor: Coda.",
            required_action="Collect at least one source specifically about Coda.",
            entity="Coda",
            dimension="competitor coverage",
            question="pricing, collaboration",
        )
        workspace.save_run_result(
            RunResult(
                run_id=run_id,
                status="needs_more_evidence",
                review_feedback=[feedback],
                error="max_rework_attempts_exceeded",
            )
        )

        html = render_run_detail(workspace, run_id)

        assert html is not None
        assert "Reviewer Feedback Flow" in html
        assert "Evidence is still missing" in html
        assert "missing_source → collector" in html
        assert "Collector → Analyst → Writer → Reviewer" in html
        assert "Entity: Coda" in html
        assert "Dimension: competitor coverage" in html
        assert "Question: pricing, collaboration" in html
        assert "Collect at least one source specifically about Coda." in html


def test_render_run_detail_returns_none_for_missing_run():
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)

        html = render_run_detail(workspace, "nonexistent_run")

        assert html is None
