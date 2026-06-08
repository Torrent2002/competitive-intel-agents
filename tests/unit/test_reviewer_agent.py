from competitive_intel_agents.agents import ReviewerAgent
from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.harness import InMemoryCheckpointStore, RuntimeHarness
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AgentProfile,
    AgentState,
    AnalysisClaim,
    CompetitiveIntelRequest,
    ReportDraft,
    RunContext,
    SourceArtifact,
)
from competitive_intel_agents.runtime import ToolRuntime


def make_context(run_id: str = "run_001") -> RunContext:
    return RunContext(
        run_id=run_id,
        request=CompetitiveIntelRequest(company="Acme", competitors=["Beta"]),
        agent_profiles={
            "reviewer": AgentProfile(
                agent="reviewer",
                max_rounds=2,
                allowed_tools=[],
            )
        },
    )


def save_source(store: InMemoryArtifactStore, source_id: str = "source_001") -> None:
    store.save_source(
        SourceArtifact(
            id=source_id,
            run_id="run_001",
            url=f"https://example.com/{source_id}",
            title="Example source",
            snippet="Evidence snippet.",
        )
    )


def save_claim(
    store: InMemoryArtifactStore,
    claim_id: str = "claim_001",
    source_ids: list[str] | None = None,
) -> None:
    store.save_claim(
        AnalysisClaim(
            id=claim_id,
            run_id="run_001",
            text="Beta has a published team plan.",
            source_ids=source_ids or ["source_001"],
            confidence="high",
            reasoning="The source describes the plan.",
        )
    )


def save_report(
    store: InMemoryArtifactStore,
    sections: dict[str, str] | None = None,
    claim_ids: list[str] | None = None,
    source_ids: list[str] | None = None,
) -> None:
    store.save_report(
        ReportDraft(
            id="report_run_001_001",
            run_id="run_001",
            sections=sections
            or {
                "Overview": "Summary.",
                "Feature comparison": "Comparison.",
                "Pricing": "Pricing.",
                "SWOT": "SWOT.",
                "Sources": "- source_001",
            },
            claim_ids=claim_ids or ["claim_001"],
            source_ids=source_ids or ["source_001"],
        )
    )


def test_reviewer_approves_fully_sourced_report() -> None:
    store = InMemoryArtifactStore()
    save_source(store)
    save_claim(store)
    save_report(store)

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is True
    assert result.signals == ["approved"]
    assert result.output_artifact_ids == ["report_run_001_001"]
    assert result.tool_calls == []
    assert result.review_feedback == []


def test_reviewer_rejects_missing_sections_with_writer_feedback() -> None:
    store = InMemoryArtifactStore()
    save_source(store)
    save_claim(store)
    save_report(
        store,
        sections={
            "Overview": "Summary.",
            "Feature comparison": "Comparison.",
            "SWOT": "SWOT.",
            "Sources": "- source_001",
        },
    )

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is False
    assert result.signals == ["rework_required"]
    assert result.review_feedback[0].issue == "missing_section"
    assert result.review_feedback[0].target_agent == "writer"
    assert result.review_feedback[0].target_artifact_id == "report_run_001_001"


def test_reviewer_rejects_unknown_report_claim_with_analyst_feedback() -> None:
    store = InMemoryArtifactStore()
    save_source(store)
    save_report(store, claim_ids=["claim_missing"])

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is False
    assert result.review_feedback[0].issue == "unsupported_claim"
    assert result.review_feedback[0].target_agent == "analyst"
    assert result.review_feedback[0].target_artifact_id == "claim_missing"


def test_reviewer_routes_missing_source_to_collector() -> None:
    store = InMemoryArtifactStore()
    save_claim(store, source_ids=["source_missing"])
    save_report(store, source_ids=["source_missing"])

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is False
    assert result.review_feedback[0].issue == "missing_source"
    assert result.review_feedback[0].target_agent == "collector"
    assert result.review_feedback[0].target_artifact_id == "source_missing"


def test_reviewer_rejects_report_source_ids_not_covered_by_claims() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001")
    save_source(store, "source_002")
    save_claim(store, source_ids=["source_001"])
    save_report(store, source_ids=["source_001", "source_002"])

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is False
    assert result.review_feedback[0].issue == "unsupported_claim"
    assert result.review_feedback[0].target_agent == "analyst"
    assert result.review_feedback[0].target_artifact_id == "report_run_001_001"


def test_reviewer_can_run_through_harness_without_tools() -> None:
    store = InMemoryArtifactStore()
    save_source(store)
    save_claim(store)
    save_report(store)
    context = make_context()
    harness = RuntimeHarness(
        InMemoryJournalStore(),
        ToolRuntime(),
        InMemoryCheckpointStore(),
    )

    result = harness.run_agent(context, ReviewerAgent(store))

    assert result.agent == "reviewer"
    assert result.decision == "stop"
    assert result.output_artifact_ids == ["report_run_001_001"]
