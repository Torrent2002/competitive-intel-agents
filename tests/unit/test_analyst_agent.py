import json

from competitive_intel_agents.agents import AnalystAgent
from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.harness import RuntimeHarness
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AgentProfile,
    AgentState,
    AnalysisClaim,
    CompetitiveIntelRequest,
    ModelResponse,
    RunContext,
    SourceArtifact,
)
from competitive_intel_agents.runtime import ToolRuntime


def context_payload(model_request):
    return json.loads(model_request.messages[1]["content"].split("Context JSON:\n", 1)[1])


class CapturingModelRuntime:
    def __init__(self, parsed):
        self.parsed = parsed
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ModelResponse(ok=True, parsed=self.parsed)


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


def make_single_company_context(max_rounds: int = 2) -> RunContext:
    return RunContext(
        run_id="run_001",
        request=CompetitiveIntelRequest(
            company="ACME",
            market="collaboration software",
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
    entity: str | None = None,
    metadata: dict | None = None,
) -> None:
    source_metadata = dict(metadata or {})
    if entity:
        source_metadata["entity"] = entity
    store.save_source(
        SourceArtifact(
            id=source_id,
            run_id="run_001",
            url=url,
            title=title,
            snippet=snippet,
            metadata=source_metadata,
        )
    )


def test_analyst_waits_for_sources_without_calling_tools() -> None:
    store = InMemoryArtifactStore()
    analyst = AnalystAgent(store)

    result = analyst.run_round(make_context(), AgentState(agent="analyst", round=1))

    # Analyst signals missing_sources and yields control immediately;
    # the orchestrator's collector_coverage_feedback path is responsible
    # for routing the missing-evidence problem back to the collector via
    # rework, so the analyst itself reports completed=True with no claims.
    assert result.completed is True
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
    context = make_single_company_context()

    first = analyst.run_round(context, AgentState(agent="analyst", round=1))
    second = analyst.run_round(context, AgentState(agent="analyst", round=2))

    assert first.output_artifact_ids == ["claim_run_001_001"]
    assert second.output_artifact_ids == []
    assert second.completed is True
    assert len(store.list_claims("run_001")) == 1


def test_analyst_adds_claim_for_unclaimed_competitor_source() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001", entity="ACME")
    save_source(
        store,
        "source_002",
        title="Globex source",
        snippet="Globex has competitor evidence.",
        entity="Globex",
    )
    store.save_claim(
        AnalysisClaim(
            id="claim_run_001_001",
            run_id="run_001",
            text="ACME has sourced evidence.",
            source_ids=["source_001"],
        )
    )
    analyst = AnalystAgent(store, target_claims=1)

    result = analyst.run_round(make_context(), AgentState(agent="analyst", round=2))

    assert result.completed is True
    assert result.output_artifact_ids == ["claim_run_001_002"]
    assert store.list_claims("run_001")[-1].source_ids == ["source_002"]


def test_analyst_prioritizes_required_entity_sources_before_filler_sources() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001", entity="ACME")
    save_source(store, "source_002", entity="ACME")
    save_source(store, "source_003", entity=None)
    save_source(
        store,
        "source_004",
        title="Globex source",
        snippet="Globex competitor evidence.",
        entity="Globex",
    )
    analyst = AnalystAgent(store, target_claims=2)

    result = analyst.run_round(make_context(), AgentState(agent="analyst", round=1))

    assert result.completed is True
    assert "source_004" in {
        source_id
        for claim in store.list_claims("run_001")
        for source_id in claim.source_ids
    }


def test_analyst_can_run_through_harness_without_tools() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001")
    analyst = AnalystAgent(store, target_claims=1)
    harness = RuntimeHarness(InMemoryJournalStore(), ToolRuntime())

    result = harness.run_agent(make_single_company_context(max_rounds=2), analyst)

    assert result.decision == "stop"
    assert result.output_artifact_ids == ["claim_run_001_001"]
    assert len(store.list_claims("run_001")) == 1


def test_analyst_model_context_includes_request_coverage_and_source_metadata() -> None:
    store = InMemoryArtifactStore()
    save_source(
        store,
        "source_001",
        entity="ACME",
        metadata={
            "dimension": "pricing",
            "content_ref": "content/run_001/source_001.txt",
            "content_hash": "abc123",
            "char_count": 2048,
            "summary": "ACME pricing summary",
            "source_type": "official",
        },
    )
    runtime = CapturingModelRuntime(
        {
            "claims": [
                {
                    "text": "ACME has published pricing evidence.",
                    "source_ids": ["source_001"],
                    "confidence": "high",
                    "reasoning": "Source includes pricing evidence.",
                }
            ]
        }
    )
    analyst = AnalystAgent(store, target_claims=1, model_runtime=runtime)

    analyst.run_round(make_context(), AgentState(agent="analyst", round=1))

    payload = context_payload(runtime.requests[0])
    assert payload["request"]["company"] == "ACME"
    assert payload["request"]["competitors"] == ["Globex"]
    assert payload["request"]["questions"] == ["pricing"]
    assert payload["coverage"]["missing_entities"] == ["Globex"]
    assert payload["sources"][0]["content_ref"] == "content/run_001/source_001.txt"
    assert payload["sources"][0]["metadata"]["char_count"] == 2048


def test_analyst_model_context_includes_content_ref_excerpt(tmp_path) -> None:
    content_file = tmp_path / "source.txt"
    content_file.write_text(
        "Audience demographics: 18-35 readers dominate. Market share: top three.",
        encoding="utf-8",
    )
    store = InMemoryArtifactStore()
    save_source(
        store,
        "source_001",
        entity="ACME",
        metadata={
            "content_ref": f"file:{content_file}",
            "char_count": content_file.stat().st_size,
        },
    )
    runtime = CapturingModelRuntime(
        {
            "claims": [
                {
                    "text": "ACME audience skews 18-35.",
                    "source_ids": ["source_001"],
                    "confidence": "high",
                    "reasoning": "Full evidence text states the demographic.",
                }
            ]
        }
    )
    analyst = AnalystAgent(store, target_claims=1, model_runtime=runtime)

    analyst.run_round(make_context(), AgentState(agent="analyst", round=1))

    payload = context_payload(runtime.requests[0])
    assert "Audience demographics" in payload["sources"][0]["content_excerpt"]
