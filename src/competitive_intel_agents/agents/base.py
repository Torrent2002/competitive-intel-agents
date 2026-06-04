"""Agent interface and access boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from competitive_intel_agents.models import (
    AgentName,
    AgentRoundResult,
    AgentState,
    RunContext,
    require_choice,
)


@runtime_checkable
class Agent(Protocol):
    """Minimal contract implemented by every agent."""

    name: AgentName

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        """Execute one agent round."""
        ...


class BaseAgent:
    """Convenience base class for concrete agents."""

    name: AgentName

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        raise NotImplementedError


@dataclass(frozen=True)
class AgentAccess:
    """Narrow access granted to an agent role."""

    may_read: frozenset[str]
    may_write: frozenset[str]
    allowed_tools: frozenset[str]


AGENT_ACCESS_MATRIX: dict[AgentName, AgentAccess] = {
    "collector": AgentAccess(
        may_read=frozenset({"run_request", "collector_sources"}),
        may_write=frozenset({"source_artifacts"}),
        allowed_tools=frozenset({"web_search", "web_fetch"}),
    ),
    "analyst": AgentAccess(
        may_read=frozenset({"source_artifacts", "analyst_review_feedback"}),
        may_write=frozenset({"analysis_claims"}),
        allowed_tools=frozenset(),
    ),
    "writer": AgentAccess(
        may_read=frozenset(
            {"analysis_claims", "source_metadata", "writer_review_feedback"}
        ),
        may_write=frozenset({"report_drafts"}),
        allowed_tools=frozenset(),
    ),
    "reviewer": AgentAccess(
        may_read=frozenset({"report_drafts", "analysis_claims", "source_artifacts"}),
        may_write=frozenset({"review_feedback"}),
        allowed_tools=frozenset(),
    ),
}


def get_agent_access(agent: AgentName) -> AgentAccess:
    require_choice(agent, set(AGENT_ACCESS_MATRIX), "agent")
    return AGENT_ACCESS_MATRIX[agent]


def ensure_tool_allowed(agent: AgentName, tool_name: str) -> None:
    access = get_agent_access(agent)
    if tool_name not in access.allowed_tools:
        raise ValueError(f"tool {tool_name} is not allowed for agent {agent}")
