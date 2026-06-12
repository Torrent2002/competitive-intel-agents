"""Run orchestration for the default competitive-intelligence DAG."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable, Protocol

from competitive_intel_agents.agents import (
    Agent,
    AnalystAgent,
    CollectorAgent,
    ReviewerAgent,
    WriterAgent,
)
from competitive_intel_agents.artifacts import ArtifactStore, InMemoryArtifactStore
from competitive_intel_agents.harness import InMemoryCheckpointStore, RuntimeHarness
from competitive_intel_agents.journal import InMemoryJournalStore, JournalStore
from competitive_intel_agents.memory import ConversationStore, InMemoryConversationStore
from competitive_intel_agents.models import (
    AgentName,
    AgentProfile,
    CompetitiveIntelRequest,
    ReviewFeedback,
    RunContext,
    RunResult,
)
from competitive_intel_agents.rework import ReworkLoop
from competitive_intel_agents.runtime import FakeWebFetch, FakeWebSearch, ToolRuntime
from competitive_intel_agents.runtime.model_runtime import ConfiguredProviderFactory, ModelRuntime


class Harness(Protocol):
    def run_agent(self, context: RunContext, agent: Agent):
        ...


class Orchestrator:
    """Create run context and execute the default agent DAG through the harness."""

    DEFAULT_DAG: tuple[AgentName, ...] = (
        "collector",
        "analyst",
        "writer",
        "reviewer",
    )
    REWORK_PRIORITY: tuple[AgentName, ...] = (
        "collector",
        "analyst",
        "writer",
        "reviewer",
    )

    def __init__(
        self,
        artifacts: ArtifactStore | None = None,
        journal: JournalStore | None = None,
        harness: Harness | None = None,
        agent_profiles: dict[str, AgentProfile] | None = None,
        run_id_factory: Callable[[], str] | None = None,
        enable_rework: bool = False,
        max_rework_attempts: int = 2,
        model_runtime: ModelRuntime | None = None,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self.artifacts = artifacts or InMemoryArtifactStore()
        self.journal = journal or InMemoryJournalStore()
        self._harness = harness or self._default_harness(self.journal)
        self._agent_profiles = agent_profiles or load_agent_profiles()
        self._run_id_factory = run_id_factory or _default_run_id
        self._enable_rework = enable_rework
        self._max_rework_attempts = max_rework_attempts
        self._model_runtime = model_runtime
        self._conversation_store = conversation_store or InMemoryConversationStore()
        self._runtimes_by_agent: dict[str, ModelRuntime] = {}
        if model_runtime is not None:
            self._runtimes_by_agent["_default"] = model_runtime
        self.last_context: RunContext | None = None

    def run(self, request: CompetitiveIntelRequest) -> RunResult:
        context = RunContext(
            run_id=self._run_id_factory(),
            request=request,
            agent_profiles=self._agent_profiles,
        )
        self.last_context = context

        for agent in self._build_agents():
            result = self._harness.run_agent(context, agent)
            if result.decision == "abort":
                return RunResult(
                    run_id=context.run_id,
                    status="aborted",
                    report_id=self._latest_report_id(context.run_id),
                    review_feedback=result.review_feedback,
                    error=f"{agent.name} aborted",
                )
            if result.decision == "rework":
                if self._enable_rework:
                    return self._apply_integrated_rework(context, result.review_feedback)
                return RunResult(
                    run_id=context.run_id,
                    status="needs_rework",
                    report_id=self._latest_report_id(context.run_id),
                    review_feedback=result.review_feedback,
                )
            if agent.name == "analyst":
                feedback = self._collector_coverage_feedback(context)
                if feedback:
                    if self._enable_rework:
                        return self._apply_integrated_rework(context, [feedback])
                    return RunResult(
                        run_id=context.run_id,
                        status="needs_rework",
                        report_id=self._latest_report_id(context.run_id),
                        review_feedback=[feedback],
                    )

        return RunResult(
            run_id=context.run_id,
            status="approved",
            report_id=self._latest_report_id(context.run_id),
        )

    def _apply_integrated_rework(
        self,
        context: RunContext,
        feedback_items,
    ) -> RunResult:
        loop = ReworkLoop(
            self.artifacts,
            harness=self._harness,
            max_attempts=self._max_rework_attempts,
            journal=self.journal,
            model_runtime=self._model_runtime,
            conversation_store=self._conversation_store,
            runtime_for_agent=self._runtime_for,
        )
        remaining_feedback = list(feedback_items)
        # ReworkLoop tracks per-(issue, target_agent, target_artifact_id)
        # attempts internally and returns status="max_attempts_exceeded"
        # once a feedback triple has consumed its budget — let it own that
        # bookkeeping rather than gate-keeping a second time here, which
        # would cut the per-feedback retry budget in half (the loop's
        # _max_attempts default is 2; an outer "seen once → stalemate"
        # gate would cap it at 1).
        for _ in range(self._max_rework_attempts):
            if not remaining_feedback:
                break
            selected_feedback = self._select_upstream_feedback(remaining_feedback)
            rework_result = loop.apply(context, selected_feedback, all_feedback=remaining_feedback)
            if rework_result.status != "applied":
                return RunResult(
                    run_id=context.run_id,
                    status=self._status_for_unresolved_feedback(remaining_feedback),
                    report_id=self._latest_report_id(context.run_id),
                    review_feedback=remaining_feedback,
                    error=rework_result.status,
                )
            if rework_result.final_decision == "stop":
                return RunResult(
                    run_id=context.run_id,
                    status="approved",
                    report_id=self._latest_report_id(context.run_id),
                )
            latest_reviewer = self.journal.list_agent_events(
                context.run_id,
                "reviewer",
            )[-1:]
            if latest_reviewer and latest_reviewer[0].decision == "stop":
                return RunResult(
                    run_id=context.run_id,
                    status="approved",
                    report_id=self._latest_report_id(context.run_id),
                )
            if latest_reviewer and latest_reviewer[0].review_feedback:
                remaining_feedback = latest_reviewer[0].review_feedback
        return RunResult(
            run_id=context.run_id,
            status=self._status_for_unresolved_feedback(remaining_feedback),
            report_id=self._latest_report_id(context.run_id),
            review_feedback=remaining_feedback,
            error="max_rework_attempts_exceeded",
        )

    def _select_upstream_feedback(
        self,
        feedback_items: list[ReviewFeedback],
    ) -> ReviewFeedback:
        for agent in self.REWORK_PRIORITY:
            for feedback in feedback_items:
                if feedback.target_agent == agent and feedback.blocking:
                    return feedback
            for feedback in feedback_items:
                if feedback.target_agent == agent:
                    return feedback
        return feedback_items[0]

    @staticmethod
    def _status_for_unresolved_feedback(
        feedback_items: list[ReviewFeedback],
    ) -> str:
        if feedback_items and all(
            item.target_agent == "collector"
            and item.issue == "missing_source"
            and item.blocking
            for item in feedback_items
        ):
            return "needs_more_evidence"
        return "rework_failed"

    def _runtime_for(self, agent_name: str) -> ModelRuntime | None:
        """Get ModelRuntime for a specific agent, using per-agent model config."""
        if self._model_runtime is None:
            return None
        if agent_name not in self._runtimes_by_agent:
            try:
                factory = ConfiguredProviderFactory()
                provider = factory.create_for_agent(agent_name)
                self._runtimes_by_agent[agent_name] = ModelRuntime(provider=provider)
            except (ValueError, RuntimeError):
                self._runtimes_by_agent[agent_name] = self._model_runtime
        return self._runtimes_by_agent.get(agent_name, self._model_runtime)

    def _build_agents(self) -> list[Agent]:
        cs = self._conversation_store
        target_sources = 10 if self._model_runtime is not None else 2
        return [
            CollectorAgent(
                self.artifacts, target_sources=target_sources,
                model_runtime=self._runtime_for("collector"),
            ),
            AnalystAgent(
                self.artifacts, model_runtime=self._runtime_for("analyst"),
                conversation_store=cs,
            ),
            WriterAgent(
                self.artifacts, model_runtime=self._runtime_for("writer"),
                conversation_store=cs,
            ),
            ReviewerAgent(
                self.artifacts, journal=self.journal,
                model_runtime=self._runtime_for("reviewer"),
                conversation_store=cs,
            ),
        ]

    def _latest_report_id(self, run_id: str) -> str | None:
        report = self.artifacts.get_latest_report(run_id)
        if report is None:
            return None
        return report.id

    def _collector_coverage_feedback(
        self,
        context: RunContext,
    ) -> ReviewFeedback | None:
        latest_collector = self.journal.list_agent_events(
            context.run_id,
            "collector",
        )[-1:]
        collector_signals = latest_collector[0].signals if latest_collector else []
        if not latest_collector or not (
            "coverage_partial" in collector_signals
            or "search_exhausted" in collector_signals
        ):
            return None

        missing = self._missing_source_entities(context)
        if missing:
            missing_text = ", ".join(missing)
            message = (
                "Analyst cannot complete a balanced competitive analysis because "
                f"collector coverage is partial for: {missing_text}."
            )
            action = (
                "Collect additional official, product, pricing, and comparison "
                f"sources for: {missing_text}."
            )
        else:
            message = (
                "Analyst cannot complete a balanced competitive analysis because "
                "collector coverage is partial."
            )
            action = (
                "Collect additional sources covering the requested company, "
                "competitors, and key comparison dimensions before writing."
            )

        return ReviewFeedback(
            issue="missing_source",
            target_agent="collector",
            target_artifact_id="collector_coverage",
            message=message,
            required_action=action,
            severity="blocking",
            blocking=True,
        )

    def _missing_source_entities(self, context: RunContext) -> list[str]:
        covered = {
            source.metadata.get("entity")
            for source in self.artifacts.list_sources(context.run_id)
            if isinstance(source.metadata.get("entity"), str)
        }
        required = [context.request.company, *context.request.competitors]
        return [entity for entity in required if entity not in covered]

    @staticmethod
    def _default_harness(journal: JournalStore) -> RuntimeHarness:
        tools = ToolRuntime()
        tools.register(FakeWebSearch())
        tools.register(FakeWebFetch())
        return RuntimeHarness(journal, tools, InMemoryCheckpointStore())


def load_agent_profiles(path: str | Path | None = None) -> dict[str, AgentProfile]:
    """Load the simple checked-in profile config without adding a YAML dependency."""

    config_path = Path(path) if path is not None else _default_profile_path()
    return _parse_agent_profiles(config_path.read_text(encoding="utf-8"))


def _parse_agent_profiles(text: str) -> dict[str, AgentProfile]:
    profiles: dict[str, dict[str, object]] = {}
    current_agent: str | None = None
    current_list_key: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if not line.startswith(" ") and line.endswith(":"):
            current_agent = line[:-1]
            profiles[current_agent] = {}
            current_list_key = None
            continue
        if current_agent is None:
            continue

        stripped = line.strip()
        if stripped.startswith("- ") and current_list_key is not None:
            profiles[current_agent].setdefault(current_list_key, [])
            profiles[current_agent][current_list_key].append(stripped[2:])
            continue
        if ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        value = value.strip()
        if value == "[]":
            profiles[current_agent][key] = []
            current_list_key = None
        elif value == "":
            profiles[current_agent][key] = []
            current_list_key = key
        elif value.isdigit():
            profiles[current_agent][key] = int(value)
            current_list_key = None
        else:
            profiles[current_agent][key] = value
            current_list_key = None

    return {
        agent: AgentProfile(
            agent=agent,
            max_rounds=int(data.get("max_rounds", 1)),
            allowed_tools=list(data.get("allowed_tools", [])),
            model=str(data.get("model", "fake")),
            strategy=str(data.get("strategy", "")),
        )
        for agent, data in profiles.items()
    }


def _default_profile_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "agent_profiles.yaml"


def _default_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


__all__ = ["Orchestrator", "load_agent_profiles"]
