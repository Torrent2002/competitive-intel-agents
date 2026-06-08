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
from competitive_intel_agents.models import (
    AgentName,
    AgentProfile,
    CompetitiveIntelRequest,
    RunContext,
    RunResult,
)
from competitive_intel_agents.runtime import FakeWebFetch, FakeWebSearch, ToolRuntime


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

    def __init__(
        self,
        artifacts: ArtifactStore | None = None,
        journal: JournalStore | None = None,
        harness: Harness | None = None,
        agent_profiles: dict[str, AgentProfile] | None = None,
        run_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.artifacts = artifacts or InMemoryArtifactStore()
        self.journal = journal or InMemoryJournalStore()
        self._harness = harness or self._default_harness(self.journal)
        self._agent_profiles = agent_profiles or load_agent_profiles()
        self._run_id_factory = run_id_factory or _default_run_id
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
                return RunResult(
                    run_id=context.run_id,
                    status="needs_rework",
                    report_id=self._latest_report_id(context.run_id),
                    review_feedback=result.review_feedback,
                )

        return RunResult(
            run_id=context.run_id,
            status="approved",
            report_id=self._latest_report_id(context.run_id),
        )

    def _build_agents(self) -> list[Agent]:
        return [
            CollectorAgent(self.artifacts),
            AnalystAgent(self.artifacts),
            WriterAgent(self.artifacts),
            ReviewerAgent(self.artifacts),
        ]

    def _latest_report_id(self, run_id: str) -> str | None:
        report = self.artifacts.get_latest_report(run_id)
        if report is None:
            return None
        return report.id

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
