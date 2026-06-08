from competitive_intel_agents.agents import WriterAgent
from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.harness import RuntimeHarness
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AgentProfile,
    AgentState,
    AnalysisClaim,
    CompetitiveIntelRequest,
    RunContext,
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
            "writer": AgentProfile(
                agent="writer",
                max_rounds=max_rounds,
                allowed_tools=[],
            )
        },
    )


def save_claim(
    store: InMemoryArtifactStore,
    claim_id: str,
    text: str,
    source_ids: list[str],
    confidence: str = "medium",
) -> None:
    store.save_claim(
        AnalysisClaim(
            id=claim_id,
            run_id="run_001",
            text=text,
            source_ids=source_ids,
            confidence=confidence,
            reasoning=f"Reasoning for {claim_id}",
        )
    )


def test_writer_waits_for_claims_without_calling_tools() -> None:
    store = InMemoryArtifactStore()
    writer = WriterAgent(store)

    result = writer.run_round(make_context(), AgentState(agent="writer", round=1))

    assert result.completed is False
    assert result.tool_calls == []
    assert result.output_artifact_ids == []
    assert result.signals == ["missing_claims"]
    assert store.get_latest_report("run_001") is None


def test_writer_creates_structured_report_from_active_claims() -> None:
    store = InMemoryArtifactStore()
    save_claim(
        store,
        "claim_001",
        "ACME has a strong collaboration workflow.",
        ["source_001"],
        confidence="high",
    )
    save_claim(
        store,
        "claim_002",
        "ACME pricing is positioned for enterprise teams.",
        ["source_002"],
    )
    writer = WriterAgent(store)

    result = writer.run_round(make_context(), AgentState(agent="writer", round=1))
    report = store.get_latest_report("run_001")

    assert result.completed is True
    assert result.tool_calls == []
    assert result.output_artifact_ids == ["report_run_001_001"]
    assert report is not None
    assert set(report.sections) == {
        "Overview",
        "Feature comparison",
        "Pricing",
        "SWOT",
        "Sources",
    }
    assert report.claim_ids == ["claim_001", "claim_002"]
    assert report.source_ids == ["source_001", "source_002"]
    assert "ACME has a strong collaboration workflow." in report.sections["Overview"]
    assert "ACME pricing is positioned for enterprise teams." in report.sections["Pricing"]
    assert "Hypotheses" in report.sections["SWOT"]


def test_writer_uses_only_active_claims() -> None:
    store = InMemoryArtifactStore()
    save_claim(store, "claim_active", "Active claim.", ["source_active"])
    save_claim(store, "claim_rejected", "Rejected claim.", ["source_rejected"])
    store.mark_rejected("claim_rejected", "Unsupported claim")
    writer = WriterAgent(store)

    writer.run_round(make_context(), AgentState(agent="writer", round=1))
    report = store.get_latest_report("run_001")

    assert report is not None
    assert report.claim_ids == ["claim_active"]
    assert report.source_ids == ["source_active"]
    assert "Rejected claim." not in "\n".join(report.sections.values())


def test_writer_does_not_duplicate_existing_report() -> None:
    store = InMemoryArtifactStore()
    save_claim(store, "claim_001", "ACME has evidence.", ["source_001"])
    writer = WriterAgent(store)
    context = make_context()

    first = writer.run_round(context, AgentState(agent="writer", round=1))
    second = writer.run_round(context, AgentState(agent="writer", round=2))

    assert first.output_artifact_ids == ["report_run_001_001"]
    assert second.output_artifact_ids == []
    assert second.completed is True
    assert store.get_latest_report("run_001").id == "report_run_001_001"


def test_writer_can_run_through_harness_without_tools() -> None:
    store = InMemoryArtifactStore()
    save_claim(store, "claim_001", "ACME has evidence.", ["source_001"])
    writer = WriterAgent(store)
    harness = RuntimeHarness(InMemoryJournalStore(), ToolRuntime())

    result = harness.run_agent(make_context(max_rounds=2), writer)

    assert result.decision == "stop"
    assert result.output_artifact_ids == ["report_run_001_001"]
    assert store.get_latest_report("run_001") is not None
