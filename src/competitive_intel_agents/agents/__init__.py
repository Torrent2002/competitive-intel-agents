"""Agent implementations and shared agent contracts."""

from competitive_intel_agents.agents.base import (
    AGENT_ACCESS_MATRIX,
    Agent,
    AgentAccess,
    BaseAgent,
    ensure_tool_allowed,
    get_agent_access,
)
from competitive_intel_agents.agents.analyst import AnalystAgent
from competitive_intel_agents.agents.collector import CollectorAgent
from competitive_intel_agents.agents.reviewer import ReviewerAgent
from competitive_intel_agents.agents.writer import WriterAgent

__all__ = [
    "AGENT_ACCESS_MATRIX",
    "Agent",
    "AgentAccess",
    "AnalystAgent",
    "BaseAgent",
    "CollectorAgent",
    "ReviewerAgent",
    "WriterAgent",
    "ensure_tool_allowed",
    "get_agent_access",
]
