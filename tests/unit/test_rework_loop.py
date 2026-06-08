from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.harness import RuntimeHarness
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AgentProfile,
    AnalysisClaim,
    CompetitiveIntelRequest,
    ReportDraft,
    ReviewFeedback,
    RunContext,
    SourceArtifact,
)
from competitive_intel_agents.rework import ReworkLoop, route_feedback
from competitive_intel_agents.runtime import ToolRuntime


def make_context() -> RunContext:
    return RunContext(
        run_id="run_001",
        request=CompetitiveIntelRequest(company="ACME", questions=["pricing"]),
        agent_profiles={
            "collector": AgentProfile(
                agent="collector",
                max_rounds=1,
                allowed_tools=["web_search", "web_fetch"],
            ),
            "analyst": AgentProfile(agent="analyst", max_rounds=2, allowed_tools=[]),
            "writer": AgentProfile(agent="writer", max_rounds=2, allowed_tools=[]),
            "reviewer": AgentProfile(agent="reviewer", max_rounds=2, allowed_tools=[]),
        },
    )


def save_report_fixture(store: InMemoryArtifactStore) -> None:
    store.save_source(
        SourceArtifact(
            id="source_001",
            run_id="run_001",
            url="https://example.com/source",
            title="Source",
            snippet="Pricing evidence.",
        )
    )
    store.save_claim(
        AnalysisClaim(
            id="claim_001",
            run_id="run_001",
            text="ACME has pricing evidence.",
            source_ids=["source_001"],
        )
    )
    store.save_report(
        ReportDraft(
            id="report_001",
            run_id="run_001",
            sections={
                "Overview": "Summary.",
                "Feature comparison": "Comparison.",
                "SWOT": "SWOT.",
                "Sources": "- source_001",
            },
            claim_ids=["claim_001"],
            source_ids=["source_001"],
        )
    )


def feedback(
    issue: str = "missing_section",
    target_agent: str = "writer",
    target_artifact_id: str = "report_001",
) -> ReviewFeedback:
    return ReviewFeedback(
        issue=issue,
        target_agent=target_agent,
        target_artifact_id=target_artifact_id,
        message="Missing required section: Pricing.",
        required_action="Add a Pricing section.",
    )


def test_routes_feedback_to_target_and_downstream_stages() -> None:
    assert route_feedback(feedback("missing_source", "collector", "source_001")) == [
        "collector",
        "analyst",
        "writer",
        "reviewer",
    ]
    assert route_feedback(feedback("unsupported_claim", "analyst", "claim_001")) == [
        "analyst",
        "writer",
        "reviewer",
    ]
    assert route_feedback(feedback("format_violation", "writer", "report_001")) == [
        "writer",
        "reviewer",
    ]


def test_rework_supersedes_report_and_reruns_writer_then_reviewer() -> None:
    store = InMemoryArtifactStore()
    save_report_fixture(store)
    harness = RuntimeHarness(InMemoryJournalStore(), ToolRuntime())
    loop = ReworkLoop(store, harness=harness)

    result = loop.apply(make_context(), feedback())

    assert result.status == "applied"
    assert result.route == ["writer", "reviewer"]
    assert result.replacement_artifact_ids == ["report_001_v2"]
    assert store.get_artifact("report_001").status == "superseded"
    replacement = store.get_artifact("report_001_v2")
    assert replacement.version == 2
    assert replacement.supersedes_id == "report_001"
    assert replacement.sections["Pricing"] == "Add a Pricing section."

    events = harness._journal.list_run_events("run_001")
    assert [event.agent for event in events] == ["writer", "reviewer"]
    assert events[-1].decision == "stop"


def test_rework_stops_after_max_attempts_for_same_feedback() -> None:
    store = InMemoryArtifactStore()
    save_report_fixture(store)
    loop = ReworkLoop(store, harness=RuntimeHarness(InMemoryJournalStore(), ToolRuntime()), max_attempts=1)
    context = make_context()
    item = feedback()

    first = loop.apply(context, item)
    second = loop.apply(context, item)

    assert first.status == "applied"
    assert second.status == "max_attempts_exceeded"
    assert second.route == []


def test_rework_rejects_stale_downstream_report_for_analyst_feedback() -> None:
    store = InMemoryArtifactStore()
    save_report_fixture(store)
    harness = RuntimeHarness(InMemoryJournalStore(), ToolRuntime())
    loop = ReworkLoop(store, harness=harness)

    result = loop.apply(
        make_context(),
        feedback("unsupported_claim", "analyst", "claim_001"),
    )

    assert result.status == "applied"
    assert result.route == ["analyst", "writer", "reviewer"]
    assert store.get_artifact("claim_001").status == "superseded"
    assert store.get_artifact("claim_001_v2").supersedes_id == "claim_001"
    assert store.get_artifact("report_001").status == "rejected"
    assert store.get_latest_report("run_001").id == "report_run_001_002"
