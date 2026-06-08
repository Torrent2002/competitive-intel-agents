from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.dashboard import (
    DashboardSnapshot,
    build_dashboard_snapshot,
    render_dashboard,
)
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AnalysisClaim,
    ReportDraft,
    ReviewFeedback,
    RoundEvent,
    SourceArtifact,
    ToolCall,
)


def append_event(
    journal: InMemoryJournalStore,
    event_id: str,
    agent: str,
    round_number: int,
    decision: str,
    signals: list[str] | None = None,
    tool_calls: list[ToolCall] | None = None,
    review_feedback: list[ReviewFeedback] | None = None,
) -> None:
    journal.append(
        RoundEvent(
            id=event_id,
            run_id="run_001",
            agent=agent,
            round=round_number,
            decision=decision,
            tool_calls=tool_calls or [],
            signals=signals or [],
            review_feedback=review_feedback or [],
        )
    )


def save_artifacts(store: InMemoryArtifactStore) -> None:
    store.save_source(
        SourceArtifact(
            id="source_001",
            run_id="run_001",
            url="https://example.com/a",
            title="Source A",
            snippet="Evidence A",
        )
    )
    store.save_source(
        SourceArtifact(
            id="source_002",
            run_id="run_001",
            url="https://example.com/b",
            title="Source B",
            snippet="Evidence B",
        )
    )
    store.save_claim(
        AnalysisClaim(
            id="claim_001",
            run_id="run_001",
            text="Claim one.",
            source_ids=["source_001"],
        )
    )
    store.save_report(
        ReportDraft(
            id="report_001",
            run_id="run_001",
            sections={"Overview": "Summary."},
            claim_ids=["claim_001"],
            source_ids=["source_001"],
        )
    )


def test_dashboard_summarizes_rounds_by_agent_and_tool_calls() -> None:
    journal = InMemoryJournalStore()
    store = InMemoryArtifactStore()
    save_artifacts(store)
    append_event(
        journal,
        "event_001",
        "collector",
        1,
        "continue",
        ["search_requested"],
        [
            ToolCall(
                id="tool_001",
                name="web_search",
                args={"query": "ACME"},
                requested_by="collector",
            )
        ],
    )
    append_event(
        journal,
        "event_002",
        "collector",
        2,
        "stop",
        ["sources_ready"],
    )
    append_event(journal, "event_003", "analyst", 1, "stop", ["claims_created"])
    append_event(journal, "event_004", "writer", 1, "stop", ["report_created"])
    append_event(journal, "event_005", "reviewer", 1, "stop", ["approved"])

    snapshot = build_dashboard_snapshot(journal, store, "run_001")

    assert snapshot.run_id == "run_001"
    assert snapshot.status == "completed"
    assert snapshot.agent_rounds == {
        "collector": 2,
        "analyst": 1,
        "writer": 1,
        "reviewer": 1,
    }
    assert snapshot.tool_call_count == 1
    assert snapshot.source_count == 2
    assert snapshot.claim_count == 1
    assert snapshot.report_id == "report_001"
    assert snapshot.health_signals == [
        "search_requested",
        "sources_ready",
        "claims_created",
        "report_created",
        "approved",
    ]


def test_dashboard_shows_rework_state_and_feedback_count() -> None:
    journal = InMemoryJournalStore()
    store = InMemoryArtifactStore()
    feedback = ReviewFeedback(
        issue="missing_section",
        target_agent="writer",
        target_artifact_id="report_001",
        message="Missing Pricing.",
        required_action="Add Pricing.",
    )
    append_event(
        journal,
        "event_001",
        "reviewer",
        1,
        "rework",
        ["rework_required"],
        review_feedback=[feedback],
    )

    snapshot = build_dashboard_snapshot(journal, store, "run_001")
    rendered = render_dashboard(snapshot)

    assert snapshot.status == "needs_rework"
    assert snapshot.review_feedback_count == 1
    assert "Status: needs_rework" in rendered
    assert "Reviewer feedback: 1" in rendered


def test_dashboard_shows_abort_state() -> None:
    journal = InMemoryJournalStore()
    store = InMemoryArtifactStore()
    append_event(journal, "event_001", "collector", 1, "abort", ["budget_exhausted"])

    snapshot = build_dashboard_snapshot(journal, store, "run_001")

    assert snapshot.status == "aborted"
    assert snapshot.health_signals == ["budget_exhausted"]


def test_dashboard_handles_empty_runs() -> None:
    snapshot = build_dashboard_snapshot(
        InMemoryJournalStore(),
        InMemoryArtifactStore(),
        "missing_run",
    )

    assert snapshot == DashboardSnapshot(run_id="missing_run", status="empty")
    assert "Run: missing_run" in render_dashboard(snapshot)
    assert "Status: empty" in render_dashboard(snapshot)
