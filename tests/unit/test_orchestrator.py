from competitive_intel_agents.agents import BaseAgent
from competitive_intel_agents.models import (
    AgentResult,
    CompetitiveIntelRequest,
    ReviewFeedback,
)
from competitive_intel_agents.orchestrator import Orchestrator


def make_request() -> CompetitiveIntelRequest:
    return CompetitiveIntelRequest(
        company="ACME",
        market="collaboration software",
        competitors=["Globex"],
        questions=["pricing"],
    )


def test_orchestrator_runs_default_dag_end_to_end_with_fake_tools() -> None:
    orchestrator = Orchestrator(run_id_factory=lambda: "run_001")

    result = orchestrator.run(make_request())

    assert result.status == "approved"
    assert result.run_id == "run_001"
    assert result.report_id == "report_run_001_001"
    assert result.review_feedback == []

    events = orchestrator.journal.list_run_events("run_001")
    first_seen_order = list(dict.fromkeys(event.agent for event in events))
    assert first_seen_order == ["collector", "analyst", "writer", "reviewer"]
    assert events[-1].agent == "reviewer"
    assert events[-1].decision == "stop"
    assert events[-1].signals == ["approved"]

    source_ids = [source.id for source in orchestrator.artifacts.list_sources("run_001")]
    assert len(source_ids) >= 2
    assert all(sid.startswith("source_run_001_") for sid in source_ids)
    assert [claim.id for claim in orchestrator.artifacts.list_claims("run_001")] == [
        "claim_run_001_001",
        "claim_run_001_002",
    ]
    assert orchestrator.artifacts.get_latest_report("run_001").id == "report_run_001_001"


def test_orchestrator_creates_run_context_with_role_bounded_profiles() -> None:
    orchestrator = Orchestrator(run_id_factory=lambda: "run_001")

    orchestrator.run(make_request())

    context = orchestrator.last_context
    assert context is not None
    assert context.agent_profiles["collector"].allowed_tools == [
        "web_search",
        "web_fetch",
    ]
    assert context.agent_profiles["analyst"].allowed_tools == []
    assert context.agent_profiles["writer"].allowed_tools == []
    assert context.agent_profiles["reviewer"].allowed_tools == []


class AbortingHarness:
    def __init__(self) -> None:
        self.agents: list[str] = []

    def run_agent(self, context, agent: BaseAgent) -> AgentResult:
        self.agents.append(agent.name)
        return AgentResult(agent=agent.name, decision="abort", rounds=1)


def test_orchestrator_aborts_when_harness_aborts() -> None:
    harness = AbortingHarness()
    orchestrator = Orchestrator(
        harness=harness,
        run_id_factory=lambda: "run_abort",
    )

    result = orchestrator.run(make_request())

    assert result.status == "aborted"
    assert result.run_id == "run_abort"
    assert result.report_id is None
    assert result.error == "collector aborted"
    assert harness.agents == ["collector"]


class ReworkHarness:
    def __init__(self) -> None:
        self.agents: list[str] = []

    def run_agent(self, context, agent: BaseAgent) -> AgentResult:
        self.agents.append(agent.name)
        if agent.name == "reviewer":
            return AgentResult(
                agent="reviewer",
                decision="rework",
                rounds=1,
                review_feedback=[
                    ReviewFeedback(
                        issue="missing_source",
                        target_agent="collector",
                        target_artifact_id="source_missing",
                        message="Missing source.",
                        required_action="Collect a replacement source.",
                    )
                ],
            )
        return AgentResult(agent=agent.name, decision="stop", rounds=1)


def test_orchestrator_returns_needs_rework_with_reviewer_feedback() -> None:
    harness = ReworkHarness()
    orchestrator = Orchestrator(
        harness=harness,
        run_id_factory=lambda: "run_rework",
    )

    result = orchestrator.run(make_request())

    assert result.status == "needs_rework"
    assert result.review_feedback[0].target_agent == "collector"
    assert harness.agents == ["collector", "analyst", "writer", "reviewer"]


def test_orchestrator_can_apply_rework_until_reviewer_approves() -> None:
    class OneShotWriterFeedbackHarness:
        def __init__(self) -> None:
            self.reviewer_calls = 0

        def run_agent(self, context, agent: BaseAgent) -> AgentResult:
            if agent.name == "reviewer":
                self.reviewer_calls += 1
                if self.reviewer_calls == 1:
                    return AgentResult(
                        agent="reviewer",
                        decision="rework",
                        rounds=1,
                        review_feedback=[
                            ReviewFeedback(
                                issue="missing_section",
                                target_agent="writer",
                                target_artifact_id="report_missing",
                                message="Missing Pricing.",
                                required_action="Add Pricing.",
                            )
                        ],
                    )
            return AgentResult(agent=agent.name, decision="stop", rounds=1)

    harness = OneShotWriterFeedbackHarness()
    orchestrator = Orchestrator(
        harness=harness,
        enable_rework=True,
        run_id_factory=lambda: "run_integrated_rework",
    )

    result = orchestrator.run(make_request())

    assert result.status == "approved"
    assert result.review_feedback == []
    assert harness.reviewer_calls == 2


def test_orchestrator_returns_rework_failed_after_max_attempts() -> None:
    harness = ReworkHarness()
    orchestrator = Orchestrator(
        harness=harness,
        enable_rework=True,
        max_rework_attempts=1,
        run_id_factory=lambda: "run_rework_failed",
    )

    result = orchestrator.run(make_request())

    assert result.status == "rework_failed"
    assert result.review_feedback[0].target_agent == "collector"
