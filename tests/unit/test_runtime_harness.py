import pytest

from competitive_intel_agents.agents import BaseAgent
from competitive_intel_agents.harness import (
    InMemoryCheckpointStore,
    RuntimeHarness,
)
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AgentProfile,
    AgentRoundResult,
    AgentState,
    CompetitiveIntelRequest,
    RunContext,
    ReviewFeedback,
    ToolCall,
)
from competitive_intel_agents.runtime import FakeWebFetch, FakeWebSearch, ToolRuntime


def make_context(
    max_rounds: int = 3,
    allowed_tools: list[str] | None = None,
) -> RunContext:
    return RunContext(
        run_id="run_001",
        request=CompetitiveIntelRequest(company="ACME"),
        agent_profiles={
            "collector": AgentProfile(
                agent="collector",
                max_rounds=max_rounds,
                allowed_tools=allowed_tools or ["web_search", "web_fetch"],
            )
        },
    )


class CompletingAgent(BaseAgent):
    name = "collector"

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        return AgentRoundResult(
            completed=True,
            output_artifact_ids=["source_001"],
            signals=["progress"],
        )


class ProgressAgent(BaseAgent):
    name = "collector"

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        return AgentRoundResult(
            completed=False,
            output_artifact_ids=[f"source_{state.round}"],
            signals=["progress"],
        )


class RepeatingToolAgent(BaseAgent):
    name = "collector"

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        return AgentRoundResult(
            tool_calls=[
                ToolCall(
                    id=f"tool_{state.round}",
                    name="web_search",
                    args={"query": "ACME market share"},
                    requested_by="collector",
                )
            ],
            signals=["tool_requested"],
        )


class DisallowedToolAgent(BaseAgent):
    name = "collector"

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        return AgentRoundResult(
            tool_calls=[
                ToolCall(
                    id="tool_disallowed",
                    name="web_search",
                    args={"query": "ACME"},
                    requested_by="collector",
                )
            ],
            signals=["tool_requested"],
        )


class ToolResultAwareAgent(BaseAgent):
    name = "collector"

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        if state.memory.get("tool_results"):
            return AgentRoundResult(
                completed=True,
                output_artifact_ids=["source_from_tool_result"],
                signals=["saw_tool_result"],
            )
        return AgentRoundResult(
            tool_calls=[
                ToolCall(
                    id="tool_search",
                    name="web_search",
                    args={"query": "ACME"},
                    requested_by="collector",
                )
            ],
            signals=["tool_requested"],
        )


class ProgressWithFailingToolAgent(BaseAgent):
    name = "collector"

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        return AgentRoundResult(
            output_artifact_ids=[f"source_{state.round}"],
            tool_calls=[
                ToolCall(
                    id=f"tool_missing_{state.round}",
                    name="missing_tool",
                    args={},
                    requested_by="collector",
                )
            ],
            signals=["progress"],
        )


class AlternateFetchAfterErrorAgent(BaseAgent):
    name = "collector"

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        return AgentRoundResult(
            tool_calls=[
                ToolCall(
                    id=f"tool_missing_{state.round}",
                    name="missing_tool",
                    args={},
                    requested_by="collector",
                )
            ],
            signals=["alternate_fetch_after_error"],
        )


class ReworkAgent(BaseAgent):
    name = "reviewer"

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        return AgentRoundResult(
            completed=False,
            signals=["rework_required"],
            review_feedback=[
                ReviewFeedback(
                    issue="missing_section",
                    target_agent="writer",
                    target_artifact_id="report_001",
                    message="Missing Pricing.",
                    required_action="Add Pricing.",
                )
            ],
        )


def make_harness() -> tuple[RuntimeHarness, InMemoryJournalStore, InMemoryCheckpointStore]:
    journal = InMemoryJournalStore()
    checkpoints = InMemoryCheckpointStore()
    tools = ToolRuntime()
    tools.register(FakeWebSearch())
    tools.register(FakeWebFetch())
    return RuntimeHarness(journal, tools, checkpoints), journal, checkpoints


def test_run_agent_stops_when_agent_completes() -> None:
    harness, journal, checkpoints = make_harness()

    result = harness.run_agent(make_context(), CompletingAgent())

    assert result.decision == "stop"
    assert result.rounds == 1
    assert result.output_artifact_ids == ["source_001"]
    assert journal.list_run_events("run_001")[0].decision == "stop"
    assert len(checkpoints.list_checkpoints("run_001", "collector")) == 1


def test_run_agent_aborts_after_round_budget_is_exhausted() -> None:
    harness, journal, checkpoints = make_harness()

    result = harness.run_agent(make_context(max_rounds=2), ProgressAgent())

    assert result.decision == "abort"
    assert result.rounds == 2
    assert [event.decision for event in journal.list_run_events("run_001")] == [
        "continue",
        "abort",
    ]
    assert len(checkpoints.list_checkpoints("run_001", "collector")) == 2


def test_repeated_identical_tool_calls_trip_circuit_breaker() -> None:
    harness, journal, _ = make_harness()

    result = harness.run_agent(make_context(max_rounds=5), RepeatingToolAgent())

    events = journal.list_run_events("run_001")
    assert result.decision == "abort"
    assert result.rounds == 3
    assert events[-1].decision == "abort"
    assert "repeated_tool_call" in events[-1].signals
    assert events[-1].tool_calls[0].signature


def test_repeated_tool_call_counts_are_isolated_by_run_id() -> None:
    harness, journal, _ = make_harness()

    first = harness.run_agent(make_context(max_rounds=2), RepeatingToolAgent())
    second_context = RunContext(
        run_id="run_002",
        request=CompetitiveIntelRequest(company="ACME"),
        agent_profiles={
            "collector": AgentProfile(
                agent="collector",
                max_rounds=1,
                allowed_tools=["web_search"],
            )
        },
    )
    second = harness.run_agent(second_context, RepeatingToolAgent())

    assert first.decision == "abort"
    assert first.rounds == 2
    assert second.decision == "abort"
    assert second.rounds == 1
    assert "repeated_tool_call" not in journal.list_run_events("run_002")[0].signals


def test_run_round_passes_context_to_tool_runtime_permissions() -> None:
    harness, journal, _ = make_harness()
    context = make_context(allowed_tools=["web_fetch"])

    event = harness.run_round(context, DisallowedToolAgent(), round_index=1)

    assert event.decision == "retry"
    assert "tool_error:tool_disallowed" in event.signals
    assert journal.list_run_events("run_001") == [event]


def test_run_round_continues_when_tool_errors_are_partial_and_progress_exists() -> None:
    harness, journal, _ = make_harness()

    event = harness.run_round(
        make_context(allowed_tools=["web_search"]),
        ProgressWithFailingToolAgent(),
        round_index=1,
    )

    assert event.decision == "continue"
    assert event.output_artifact_ids == ["source_1"]
    assert "tool_error:tool_missing_1" in event.signals
    assert journal.list_run_events("run_001") == [event]


def test_final_round_stops_when_agent_completed_with_partial_tool_errors() -> None:
    class CompletedWithFailingToolAgent(BaseAgent):
        name = "collector"

        def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
            return AgentRoundResult(
                completed=True,
                output_artifact_ids=["source_partial"],
                tool_calls=[
                    ToolCall(
                        id="tool_missing_final",
                        name="missing_tool",
                        args={},
                        requested_by="collector",
                    )
                ],
                signals=["coverage_partial"],
            )

    harness, journal, _ = make_harness()

    event = harness.run_round(
        make_context(allowed_tools=["web_search"]),
        CompletedWithFailingToolAgent(),
        round_index=3,
        is_budget_final_round=True,
    )

    assert event.decision == "stop"
    assert "tool_error:tool_missing_final" in event.signals
    assert "coverage_partial" in event.signals
    assert journal.list_run_events("run_001") == [event]


def test_run_round_continues_when_agent_has_alternate_fetches_after_errors() -> None:
    harness, journal, _ = make_harness()

    event = harness.run_round(
        make_context(allowed_tools=["web_search"]),
        AlternateFetchAfterErrorAgent(),
        round_index=1,
    )

    assert event.decision == "continue"
    assert "tool_error:tool_missing_1" in event.signals
    assert "alternate_fetch_after_error" in event.signals
    assert journal.list_run_events("run_001") == [event]


def test_run_round_rejects_tool_call_requested_by_another_agent() -> None:
    class MismatchedToolAgent(BaseAgent):
        name = "collector"

        def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
            return AgentRoundResult(
                tool_calls=[
                    ToolCall(
                        id="tool_mismatch",
                        name="web_search",
                        args={"query": "ACME"},
                        requested_by="analyst",
                    )
                ],
                signals=["tool_requested"],
            )

    harness, journal, _ = make_harness()

    event = harness.run_round(make_context(), MismatchedToolAgent(), round_index=1)

    assert event.decision == "retry"
    assert "tool_error:tool_mismatch" in event.signals
    assert journal.list_run_events("run_001") == [event]


def test_run_round_appends_one_journal_event_and_checkpoint() -> None:
    harness, journal, checkpoints = make_harness()

    event = harness.run_round(make_context(), ProgressAgent(), round_index=1)

    assert event.decision == "continue"
    assert event.output_artifact_ids == ["source_1"]
    assert journal.list_agent_events("run_001", "collector") == [event]
    saved = checkpoints.list_checkpoints("run_001", "collector")
    assert len(saved) == 1
    assert saved[0].state["signals"] == ["progress"]


def test_run_agent_passes_tool_results_to_next_round_memory() -> None:
    harness, journal, _ = make_harness()

    result = harness.run_agent(make_context(max_rounds=3), ToolResultAwareAgent())

    events = journal.list_run_events("run_001")
    assert result.decision == "stop"
    assert result.rounds == 2
    assert result.output_artifact_ids == ["source_from_tool_result"]
    assert events[0].decision == "continue"
    assert events[1].signals == ["saw_tool_result"]


def test_run_agent_returns_rework_decision_with_review_feedback() -> None:
    harness, journal, _ = make_harness()
    context = RunContext(
        run_id="run_001",
        request=CompetitiveIntelRequest(company="ACME"),
        agent_profiles={
            "reviewer": AgentProfile(
                agent="reviewer",
                max_rounds=4,
                allowed_tools=[],
            )
        },
    )

    result = harness.run_agent(context, ReworkAgent())
    events = journal.list_run_events("run_001")

    assert result.decision == "rework"
    assert result.rounds == 1
    assert result.review_feedback[0].issue == "missing_section"
    assert events[0].decision == "rework"
    assert events[0].review_feedback[0].target_agent == "writer"
