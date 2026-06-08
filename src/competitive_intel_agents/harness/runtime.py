"""Runtime harness for observable, budgeted agent execution."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from competitive_intel_agents.agents import Agent
from competitive_intel_agents.journal import JournalStore
from competitive_intel_agents.models import (
    AgentName,
    AgentResult,
    AgentState,
    Checkpoint,
    HarnessDecision,
    RoundEvent,
    RunContext,
    ToolCall,
    ToolResult,
)
from competitive_intel_agents.runtime import ToolRuntime


class CheckpointStore(Protocol):
    """Storage contract for lightweight per-round checkpoints."""

    def save(self, checkpoint: Checkpoint) -> None:
        ...

    def list_checkpoints(self, run_id: str, agent: AgentName) -> list[Checkpoint]:
        ...


class InMemoryCheckpointStore:
    """In-memory checkpoint store for tests and local runs."""

    def __init__(self) -> None:
        self._checkpoints: list[Checkpoint] = []

    def save(self, checkpoint: Checkpoint) -> None:
        self._checkpoints.append(checkpoint)

    def list_checkpoints(self, run_id: str, agent: AgentName) -> list[Checkpoint]:
        return [
            checkpoint
            for checkpoint in self._checkpoints
            if checkpoint.run_id == run_id and checkpoint.agent == agent
        ]


class RuntimeHarness:
    """Wrap agent rounds with budget, tool execution, journaling, and checkpoints."""

    def __init__(
        self,
        journal: JournalStore,
        tool_runtime: ToolRuntime,
        checkpoints: CheckpointStore | None = None,
        repeated_tool_limit: int = 3,
    ) -> None:
        self._journal = journal
        self._tool_runtime = tool_runtime
        self._checkpoints = checkpoints
        self._repeated_tool_limit = repeated_tool_limit
        self._tool_signature_counts: dict[tuple[str, AgentName, str, str], int] = {}

    def run_agent(self, context: RunContext, agent: Agent) -> AgentResult:
        max_rounds = self._max_rounds(context, agent.name)
        output_artifact_ids: list[str] = []
        last_decision: HarnessDecision = "abort"
        state_memory: dict[str, object] = {}

        for round_index in range(1, max_rounds + 1):
            event = self.run_round(
                context,
                agent,
                round_index=round_index,
                is_budget_final_round=round_index == max_rounds,
                state_memory=state_memory,
            )
            output_artifact_ids.extend(event.output_artifact_ids)
            last_decision = event.decision
            if event.decision in {"stop", "abort"}:
                return AgentResult(
                    agent=agent.name,
                    decision=event.decision,
                    rounds=round_index,
                    output_artifact_ids=output_artifact_ids,
                )

        return AgentResult(
            agent=agent.name,
            decision=last_decision,
            rounds=max_rounds,
            output_artifact_ids=output_artifact_ids,
        )

    def run_round(
        self,
        context: RunContext,
        agent: Agent,
        round_index: int,
        is_budget_final_round: bool = False,
        state_memory: dict[str, object] | None = None,
    ) -> RoundEvent:
        state = AgentState(
            agent=agent.name,
            round=round_index,
            memory=dict(state_memory or {}),
        )
        result = agent.run_round(context, state)

        signed_tool_calls, tool_results, tool_error_signals = self._execute_tool_calls(
            context,
            agent.name,
            result.tool_calls,
        )
        if state_memory is not None:
            state_memory["tool_results"] = [
                tool_result.to_dict() for tool_result in tool_results
            ]
        signals = [*result.signals, *tool_error_signals]
        decision = self._decide(
            completed=result.completed,
            has_error=bool(result.error or tool_error_signals),
            run_id=context.run_id,
            agent=agent.name,
            signed_tool_calls=signed_tool_calls,
            signals=signals,
            is_budget_final_round=is_budget_final_round,
        )

        event = RoundEvent(
            id=f"{context.run_id}:{agent.name}:{round_index}",
            run_id=context.run_id,
            agent=agent.name,
            round=round_index,
            decision=decision,
            tool_calls=signed_tool_calls,
            output_artifact_ids=result.output_artifact_ids,
            signals=signals,
        )
        self._journal.append(event)
        self._save_checkpoint(context, agent.name, round_index, result.signals)
        return event

    def _execute_tool_calls(
        self,
        context: RunContext,
        agent: AgentName,
        tool_calls: list[ToolCall],
    ) -> tuple[list[ToolCall], list[ToolResult], list[str]]:
        signed_tool_calls: list[ToolCall] = []
        tool_results: list[ToolResult] = []
        tool_error_signals: list[str] = []
        for call in tool_calls:
            signature = self._tool_runtime.signature(call)
            signed_call = replace(call, signature=signature)
            signed_tool_calls.append(signed_call)
            result = self._tool_runtime.execute(agent, signed_call, context=context)
            tool_results.append(result)
            if not result.ok:
                tool_error_signals.append(f"tool_error:{call.id}")
        return signed_tool_calls, tool_results, tool_error_signals

    def _decide(
        self,
        completed: bool,
        has_error: bool,
        run_id: str,
        agent: AgentName,
        signed_tool_calls: list[ToolCall],
        signals: list[str],
        is_budget_final_round: bool,
    ) -> HarnessDecision:
        if completed:
            return "stop"
        if self._has_repeated_tool_call(run_id, agent, signed_tool_calls):
            signals.append("repeated_tool_call")
            return "abort"
        if has_error:
            return "retry"
        if is_budget_final_round:
            return "abort"
        return "continue"

    def _has_repeated_tool_call(
        self,
        run_id: str,
        agent: AgentName,
        signed_tool_calls: list[ToolCall],
    ) -> bool:
        for call in signed_tool_calls:
            key = (run_id, agent, call.name, call.signature)
            self._tool_signature_counts[key] = self._tool_signature_counts.get(key, 0) + 1
            if self._tool_signature_counts[key] >= self._repeated_tool_limit:
                return True
        return False

    def _save_checkpoint(
        self,
        context: RunContext,
        agent: AgentName,
        round_index: int,
        signals: list[str],
    ) -> None:
        if self._checkpoints is None:
            return
        self._checkpoints.save(
            Checkpoint(
                id=f"{context.run_id}:{agent}:{round_index}",
                run_id=context.run_id,
                agent=agent,
                round=round_index,
                state={"round": round_index, "signals": signals},
            )
        )

    @staticmethod
    def _max_rounds(context: RunContext, agent: AgentName) -> int:
        profile = context.agent_profiles.get(agent)
        if profile is None:
            return 1
        return profile.max_rounds
