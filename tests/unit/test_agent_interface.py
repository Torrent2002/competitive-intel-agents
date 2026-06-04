import pytest

from competitive_intel_agents.agents import (
    Agent,
    AgentAccess,
    BaseAgent,
    ensure_tool_allowed,
    get_agent_access,
)
from competitive_intel_agents.models import (
    AgentRoundResult,
    AgentState,
    CompetitiveIntelRequest,
    RunContext,
    ToolCall,
)


def make_context() -> RunContext:
    return RunContext(
        run_id="run_001",
        request=CompetitiveIntelRequest(company="Notion"),
        agent_profiles={},
    )


class CompletingAgent(BaseAgent):
    name = "collector"

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        return AgentRoundResult(
            completed=True,
            output_artifact_ids=["source_001"],
            signals=["progress"],
            message=f"completed {context.run_id} round {state.round}",
        )


class ToolRequestingAgent(BaseAgent):
    name = "collector"

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        return AgentRoundResult(
            completed=False,
            tool_calls=[
                ToolCall(
                    id="tool_001",
                    name="web_search",
                    args={"query": context.request.company},
                    requested_by=self.name,
                )
            ],
            signals=["tool_requested"],
        )


def test_fake_agent_can_complete_a_round() -> None:
    agent: Agent = CompletingAgent()

    assert isinstance(agent, Agent)

    result = agent.run_round(make_context(), AgentState(agent="collector", round=1))

    assert result.completed is True
    assert result.output_artifact_ids == ["source_001"]
    assert result.signals == ["progress"]


def test_fake_agent_can_request_tool_calls() -> None:
    result = ToolRequestingAgent().run_round(
        make_context(),
        AgentState(agent="collector", round=1),
    )

    assert result.completed is False
    assert result.tool_calls[0].name == "web_search"
    assert result.tool_calls[0].requested_by == "collector"


def test_agent_access_boundaries_are_narrow() -> None:
    writer_access = get_agent_access("writer")
    analyst_access = get_agent_access("analyst")
    collector_access = get_agent_access("collector")

    assert isinstance(writer_access, AgentAccess)
    assert "analysis_claims" in writer_access.may_read
    assert "raw_web_pages" not in writer_access.may_read
    assert "web_search" in collector_access.allowed_tools
    assert analyst_access.allowed_tools == frozenset()


def test_tool_permissions_are_enforced_by_agent_name() -> None:
    ensure_tool_allowed("collector", "web_fetch")

    with pytest.raises(ValueError, match="not allowed"):
        ensure_tool_allowed("analyst", "web_fetch")


def test_base_agent_requires_run_round_implementation() -> None:
    class IncompleteAgent(BaseAgent):
        name = "reviewer"

    with pytest.raises(NotImplementedError):
        IncompleteAgent().run_round(make_context(), AgentState(agent="reviewer"))
