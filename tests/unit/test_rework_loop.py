from competitive_intel_agents.agents import CollectorAgent
from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.harness import RuntimeHarness
from competitive_intel_agents.journal import InMemoryJournalStore
from dataclasses import replace

from competitive_intel_agents.models import (
    AgentProfile,
    AgentState,
    AnalysisClaim,
    CompetitiveIntelRequest,
    ModelResponse,
    ReportDraft,
    ReviewFeedback,
    RunContext,
    SourceArtifact,
)
from competitive_intel_agents.rework import ReworkLoop, route_feedback
from competitive_intel_agents.runtime import ToolRuntime


class CapturingHarness:
    def __init__(self) -> None:
        self.contexts = []
        self.agents = []

    def run_agent(self, context, agent):
        self.contexts.append(context)
        self.agents.append(agent.name)
        return type(
            "AgentResult",
            (),
            {
                "decision": "stop",
            },
        )()


class CapturingModelRuntime:
    def __init__(self) -> None:
        self.agents: list[str] = []

    def complete(self, request):
        self.agents.append(request.agent)
        if request.agent == "writer":
            return ModelResponse(
                ok=True,
                parsed={
                    "sections": {
                        "Overview": "Overview [claim_001]",
                        "Feature comparison": "Comparison [claim_001]",
                        "Pricing": "Pricing [claim_001]",
                        "SWOT": "SWOT [claim_001]",
                        "Sources": "- source_001",
                    }
                },
            )
        if request.agent == "reviewer":
            return ModelResponse(ok=True, parsed={"feedback": []})
        return ModelResponse(ok=True, parsed={"claims": []})


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


def test_rework_route_preserves_model_runtime_for_downstream_agents() -> None:
    store = InMemoryArtifactStore()
    save_report_fixture(store)
    harness = RuntimeHarness(InMemoryJournalStore(), ToolRuntime())
    model_runtime = CapturingModelRuntime()
    loop = ReworkLoop(store, harness=harness, model_runtime=model_runtime)

    loop.apply(make_context(), feedback("unsupported_claim", "analyst", "claim_001"))

    assert "writer" in model_runtime.agents
    assert "reviewer" in model_runtime.agents


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


def test_collector_rework_feedback_creates_targeted_research_plan() -> None:
    store = InMemoryArtifactStore()
    save_report_fixture(store)
    harness = CapturingHarness()
    loop = ReworkLoop(store, harness=harness)
    item = ReviewFeedback(
        issue="missing_source",
        target_agent="collector",
        target_artifact_id="question_coverage:market_share",
        message="Market share and audience evidence is missing.",
        required_action="Collect market share and audience evidence from third-party reports.",
        entity="ACME",
        dimension="market_share",
        question="market share",
    )

    loop.apply(make_context(), item)

    collector_context = harness.contexts[0]
    plan = collector_context.metadata["collector_rework_plan"]
    assert plan["entity"] == "ACME"
    assert plan["dimension"] == "market_share"
    assert plan["question"] == "market share"
    assert any("market share" in query.lower() for query in plan["queries"])
    assert any("QuestMobile" in query for query in plan["queries"])


def test_collector_uses_targeted_rework_plan_before_generic_queries() -> None:
    store = InMemoryArtifactStore()
    context = replace(
        make_context(),
        metadata={
            "collector_rework_plan": {
                "entity": "ACME",
                "entity_role": "self",
                "dimension": "market_share",
                "source_type": "data_provider",
                "queries": [
                    "ACME QuestMobile market share",
                    "ACME market share MAU report",
                ],
            }
        },
    )
    collector = CollectorAgent(store)

    result = collector.run_round(context, AgentState(agent="collector", round=1))
    queries = [call.args["query"] for call in result.tool_calls]

    assert queries == [
        "ACME QuestMobile market share",
        "ACME market share MAU report",
    ]
    assert "targeted_rework_plan" in result.signals
    assert all(call.args["metadata"]["dimension"] == "market_share" for call in result.tool_calls)
