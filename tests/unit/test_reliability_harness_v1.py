from competitive_intel_agents.agents import BaseAgent
from competitive_intel_agents.harness import InMemoryCheckpointStore, RuntimeHarness
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AgentProfile,
    AgentRoundResult,
    AgentState,
    Checkpoint,
    CompetitiveIntelRequest,
    RunContext,
    ToolCall,
)
from competitive_intel_agents.runtime import ToolRuntime


def make_context(max_rounds: int = 5) -> RunContext:
    return RunContext(
        run_id="run_001",
        request=CompetitiveIntelRequest(company="ACME"),
        agent_profiles={
            "collector": AgentProfile(
                agent="collector",
                max_rounds=max_rounds,
                allowed_tools=["broken_tool"],
            )
        },
    )


class StalledAgent(BaseAgent):
    name = "collector"

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        return AgentRoundResult(completed=False, signals=["waiting"])


class BrokenToolAgent(BaseAgent):
    name = "collector"

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        return AgentRoundResult(
            tool_calls=[
                ToolCall(
                    id=f"broken_{state.round}",
                    name="broken_tool",
                    requested_by="collector",
                )
            ],
            signals=["tool_requested"],
        )


class ResumeAwareAgent(BaseAgent):
    name = "collector"

    def __init__(self) -> None:
        self.seen_rounds: list[int] = []
        self.seen_checkpoint_ids: list[str | None] = []

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        self.seen_rounds.append(state.round)
        self.seen_checkpoint_ids.append(state.last_checkpoint_id)
        return AgentRoundResult(completed=True, signals=["resumed"])


def test_stalled_read_only_rounds_emit_stall_signal_and_abort_after_retries() -> None:
    journal = InMemoryJournalStore()
    harness = RuntimeHarness(journal, ToolRuntime(), max_retries=1)

    result = harness.run_agent(make_context(max_rounds=4), StalledAgent())
    events = journal.list_run_events("run_001")

    assert result.decision == "stop"
    assert [event.decision for event in events] == ["retry", "stop"]
    assert "stalled_round" in events[0].signals
    assert "max_errors_tolerated" in events[-1].signals


def test_tool_results_are_journaled_for_diagnostics() -> None:
    journal = InMemoryJournalStore()
    harness = RuntimeHarness(journal, ToolRuntime(), max_retries=0)

    harness.run_agent(make_context(max_rounds=2), BrokenToolAgent())
    event = journal.list_run_events("run_001")[0]

    assert event.tool_results[0].tool_call_id == "broken_1"
    assert event.tool_results[0].ok is False
    assert "tool_error:broken_1" in event.signals


def test_harness_resumes_from_latest_checkpoint_round() -> None:
    journal = InMemoryJournalStore()
    checkpoints = InMemoryCheckpointStore()
    checkpoints.save(
        Checkpoint(
            id="run_001:collector:2",
            run_id="run_001",
            agent="collector",
            round=2,
            state={"signals": ["previous"]},
        )
    )
    agent = ResumeAwareAgent()
    harness = RuntimeHarness(journal, ToolRuntime(), checkpoints)

    result = harness.run_agent(make_context(max_rounds=5), agent)

    assert result.decision == "stop"
    assert agent.seen_rounds == [3]
    assert agent.seen_checkpoint_ids == ["run_001:collector:2"]
    assert "resumed_from_checkpoint:run_001:collector:2" in journal.list_run_events(
        "run_001"
    )[0].signals
