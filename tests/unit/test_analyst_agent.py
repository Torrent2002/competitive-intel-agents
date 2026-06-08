from competitive_intel_agents.agents import AnalystAgent
from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.harness import RuntimeHarness
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AgentProfile,
    AgentState,
    CompetitiveIntelRequest,
    RunContext,
    SourceArtifact,
)
from competitive_intel_agents.runtime import ToolRuntime


def make_context(max_rounds: int = 2) -> RunContext:
    return RunContext(
        run_id="run_001",
        request=CompetitiveIntelRequest(
            company="ACME",
            market="collaboration software",
            competitors=["Globex"],
            questions=["pricing"],
        ),
        agent_profiles={
            "analyst": AgentProfile(
                agent="analyst",
                max_rounds=max_rounds,
                allowed_tools=[],
            )
        },
    )


def save_source(
    store: InMemoryArtifactStore,
    source_id: str,
    url: str = "https://example.com/source",
    title: str = "ACME source",
    snippet: str = "ACME has a strong collaboration workflow.",
) -> None:
    store.save_source(
        SourceArtifact(
            id=source_id,
            run_id="run_001",
            url=url,
            title=title,
            snippet=snippet,
        )
    )


def test_analyst_waits_for_sources_without_calling_tools() -> None:
    store = InMemoryArtifactStore()
    analyst = AnalystAgent(store)

    result = analyst.run_round(make_context(), AgentState(agent="analyst", round=1))

    assert result.completed is False
    assert result.tool_calls == []
    assert result.output_artifact_ids == []
    assert result.signals == ["missing_sources"]
    assert store.list_claims("run_001") == []


def test_analyst_creates_sourced_claims_from_active_sources() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001")
    save_source(
        store,
        "source_002",
        url="https://example.com/pricing",
        title="ACME pricing",
        snippet="ACME pricing is positioned for enterprise teams.",
    )
    analyst = AnalystAgent(store, target_claims=2)

    result = analyst.run_round(make_context(), AgentState(agent="analyst", round=1))
    claims = store.list_claims("run_001")

    assert result.completed is True
    assert result.tool_calls == []
    assert result.output_artifact_ids == ["claim_run_001_001", "claim_run_001_002"]
    assert [claim.source_ids for claim in claims] == [["source_001"], ["source_002"]]
    assert all(claim.confidence == "medium" for claim in claims)
    assert claims[0].reasoning == "Derived from source source_001: ACME source"


def test_analyst_reads_only_active_sources() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_active")
    save_source(store, "source_rejected", url="https://example.com/rejected")
    store.mark_rejected("source_rejected", "Duplicate or irrelevant source")
    analyst = AnalystAgent(store, target_claims=2)

    result = analyst.run_round(make_context(), AgentState(agent="analyst", round=1))
    claims = store.list_claims("run_001")

    assert result.completed is False
    assert result.output_artifact_ids == ["claim_run_001_001"]
    assert len(claims) == 1
    assert claims[0].source_ids == ["source_active"]


def test_analyst_does_not_duplicate_existing_claim_for_same_source() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001")
    analyst = AnalystAgent(store, target_claims=1)
    context = make_context()

    first = analyst.run_round(context, AgentState(agent="analyst", round=1))
    second = analyst.run_round(context, AgentState(agent="analyst", round=2))

    assert first.output_artifact_ids == ["claim_run_001_001"]
    assert second.output_artifact_ids == []
    assert second.completed is True
    assert len(store.list_claims("run_001")) == 1


def test_analyst_can_run_through_harness_without_tools() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001")
    analyst = AnalystAgent(store, target_claims=1)
    harness = RuntimeHarness(InMemoryJournalStore(), ToolRuntime())

    result = harness.run_agent(make_context(max_rounds=2), analyst)

    assert result.decision == "stop"
    assert result.output_artifact_ids == ["claim_run_001_001"]
    assert len(store.list_claims("run_001")) == 1
