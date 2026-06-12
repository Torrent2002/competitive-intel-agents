"""Runtime harness for observable, budgeted agent execution."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from competitive_intel_agents.agents import Agent
from competitive_intel_agents.journal import JournalStore
from competitive_intel_agents.models import (
    AgentName,
    AgentRoundResult,
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
        max_retries: int = 2,
    ) -> None:
        self._journal = journal
        self._tool_runtime = tool_runtime
        self._checkpoints = checkpoints
        self._repeated_tool_limit = repeated_tool_limit
        self._max_retries = max_retries
        self._tool_signature_counts: dict[tuple[str, AgentName, str, str], int] = {}
        self._retry_counts: dict[tuple[str, AgentName, str], int] = {}

    def run_agent(self, context: RunContext, agent: Agent) -> AgentResult:
        max_rounds = self._max_rounds(context, agent.name)
        output_artifact_ids: list[str] = []
        review_feedback = []
        last_decision: HarnessDecision = "abort"
        state_memory: dict[str, object] = {}

        latest_checkpoint = self._latest_checkpoint(context.run_id, agent.name)
        start_round = latest_checkpoint.round + 1 if latest_checkpoint else 1

        for round_index in range(start_round, max_rounds + 1):
            event = self.run_round(
                context,
                agent,
                round_index=round_index,
                is_budget_final_round=round_index == max_rounds,
                state_memory=state_memory,
                last_checkpoint_id=latest_checkpoint.id if latest_checkpoint else None,
            )
            latest_checkpoint = None
            output_artifact_ids.extend(event.output_artifact_ids)
            review_feedback.extend(event.review_feedback)
            last_decision = event.decision
            if event.decision in {"stop", "rework", "abort"}:
                return AgentResult(
                    agent=agent.name,
                    decision=event.decision,
                    rounds=round_index,
                    output_artifact_ids=output_artifact_ids,
                    review_feedback=review_feedback,
                )

        return AgentResult(
            agent=agent.name,
            decision=last_decision,
            rounds=max_rounds,
            output_artifact_ids=output_artifact_ids,
            review_feedback=review_feedback,
        )

    def run_round(
        self,
        context: RunContext,
        agent: Agent,
        round_index: int,
        is_budget_final_round: bool = False,
        state_memory: dict[str, object] | None = None,
        last_checkpoint_id: str | None = None,
    ) -> RoundEvent:
        state = AgentState(
            agent=agent.name,
            round=round_index,
            memory=dict(state_memory or {}),
            last_checkpoint_id=last_checkpoint_id,
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
        if last_checkpoint_id:
            signals.append(f"resumed_from_checkpoint:{last_checkpoint_id}")
        if self._is_stalled(result):
            signals.append("stalled_round")
        decision = self._decide(
            completed=result.completed,
            has_error=bool(result.error or tool_error_signals),
            made_progress=bool(result.output_artifact_ids),
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
            tool_results=tool_results,
            output_artifact_ids=result.output_artifact_ids,
            signals=signals,
            review_feedback=result.review_feedback,
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
        made_progress: bool,
        run_id: str,
        agent: AgentName,
        signed_tool_calls: list[ToolCall],
        signals: list[str],
        is_budget_final_round: bool,
    ) -> HarnessDecision:
        if completed:
            return "stop"
        if "rework_required" in signals:
            return "rework"
        if "non_retryable_error" in signals:
            return "abort"
        if self._has_repeated_tool_call(run_id, agent, signed_tool_calls):
            signals.append("repeated_tool_call")
            return "abort"
        if has_error and made_progress and not is_budget_final_round:
            signals.append("partial_tool_error_tolerated")
            return "continue"
        if (
            has_error
            and "alternate_fetch_after_error" in signals
            and not is_budget_final_round
        ):
            signals.append("alternate_tool_error_tolerated")
            return "continue"
        if has_error or "stalled_round" in signals:
            reason = self._retry_reason(has_error, signals)
            if self._retry_exhausted(run_id, agent, reason):
                signals.append("max_errors_tolerated")
                return "stop"
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

    def _latest_checkpoint(
        self,
        run_id: str,
        agent: AgentName,
    ) -> Checkpoint | None:
        if self._checkpoints is None:
            return None
        checkpoints = self._checkpoints.list_checkpoints(run_id, agent)
        if not checkpoints:
            return None
        return max(checkpoints, key=lambda checkpoint: checkpoint.round)

    @staticmethod
    def _is_stalled(result: AgentRoundResult) -> bool:
        return (
            not result.completed
            and not result.tool_calls
            and not result.output_artifact_ids
            and "rework_required" not in result.signals
        )

    @staticmethod
    def _retry_reason(has_error: bool, signals: list[str]) -> str:
        if has_error:
            return "error"
        if "stalled_round" in signals:
            return "stall"
        return "unknown"

    def _retry_exhausted(
        self,
        run_id: str,
        agent: AgentName,
        reason: str,
    ) -> bool:
        key = (run_id, agent, reason)
        self._retry_counts[key] = self._retry_counts.get(key, 0) + 1
        return self._retry_counts[key] > self._max_retries

    def reset_retry_counts(self, agent: AgentName) -> None:
        """Clear retry counts for *agent*, giving fresh quota for rework cycles."""
        keys_to_clear = [
            key for key in self._retry_counts if key[1] == agent
        ]
        for key in keys_to_clear:
            del self._retry_counts[key]

    @staticmethod
    def _max_rounds(context: RunContext, agent: AgentName) -> int:
        profile = context.agent_profiles.get(agent)
        if profile is None:
            return 1
        return profile.max_rounds
