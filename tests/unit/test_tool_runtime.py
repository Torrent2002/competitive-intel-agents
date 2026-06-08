"""Tests for the Tool Runtime (Module 06)."""

import pytest

from competitive_intel_agents.models import (
    AgentProfile,
    CompetitiveIntelRequest,
    RunContext,
    ToolCall,
)
from competitive_intel_agents.runtime.tool_runtime import (
    FakeWebFetch,
    FakeWebSearch,
    ToolPolicy,
    ToolRuntime,
)


def make_tool_call(
    tool_id: str = "tc_001",
    name: str = "web_search",
    args: dict | None = None,
    requested_by: str = "collector",
) -> ToolCall:
    return ToolCall(
        id=tool_id,
        name=name,
        args=args or {"query": "competitor market share"},
        requested_by=requested_by,
    )


def make_context(allowed_tools: list[str]) -> RunContext:
    return RunContext(
        run_id="run_001",
        request=CompetitiveIntelRequest(company="ACME"),
        agent_profiles={
            "collector": AgentProfile(
                agent="collector",
                max_rounds=3,
                allowed_tools=allowed_tools,
            )
        },
    )


# ── Tool execution ──────────────────────────────────────────────

def test_execute_allowed_tool() -> None:
    """Collector should be able to call web_search through the runtime."""
    runtime = ToolRuntime()
    runtime.register(FakeWebSearch())
    call = make_tool_call("tc_001", "web_search", {"query": "ACME revenue 2025"})

    result = runtime.execute("collector", call)

    assert result.ok is True
    assert result.tool_call_id == "tc_001"
    assert result.error is None
    assert "results" in result.data
    assert len(result.data["results"]) > 0


def test_execute_web_fetch() -> None:
    """web_fetch should return page content."""
    runtime = ToolRuntime()
    runtime.register(FakeWebFetch())
    call = make_tool_call("tc_002", "web_fetch", {"url": "https://example.com"})

    result = runtime.execute("collector", call)

    assert result.ok is True
    assert "content" in result.data
    assert "title" in result.data


def test_reject_disallowed_tool() -> None:
    """Analyst should not be able to call web_search — only Collector can."""
    runtime = ToolRuntime()
    runtime.register(FakeWebSearch())
    call = make_tool_call("tc_003", "web_search", requested_by="analyst")

    result = runtime.execute("analyst", call)

    assert result.ok is False
    assert result.error is not None
    assert "not allowed" in result.error.lower()
    assert result.data == {}


def test_rejects_tool_call_requested_by_another_agent() -> None:
    """A call attributed to one agent cannot be executed as another agent."""
    runtime = ToolRuntime()
    runtime.register(FakeWebSearch())
    call = make_tool_call("tc_identity", "web_search", requested_by="analyst")

    result = runtime.execute("collector", call)

    assert result.ok is False
    assert result.error is not None
    assert "requested_by" in result.error
    assert result.data == {}


def test_profile_allowed_tools_can_narrow_static_role_permissions() -> None:
    """Run profiles are effective permissions and may remove role-default tools."""
    runtime = ToolRuntime(policy=ToolPolicy())
    runtime.register(FakeWebSearch())
    runtime.register(FakeWebFetch())

    search = make_tool_call("tc_search", "web_search", {"query": "ACME"})
    fetch = make_tool_call("tc_fetch", "web_fetch", {"url": "https://example.com"})
    context = make_context(allowed_tools=["web_fetch"])

    search_result = runtime.execute("collector", search, context=context)
    fetch_result = runtime.execute("collector", fetch, context=context)

    assert search_result.ok is False
    assert "not allowed" in search_result.error.lower()
    assert fetch_result.ok is True


def test_profile_allowed_tools_cannot_exceed_static_role_permissions() -> None:
    """Run profiles cannot grant tools outside the agent's role ceiling."""
    runtime = ToolRuntime(policy=ToolPolicy())
    runtime.register(FakeWebSearch())
    context = RunContext(
        run_id="run_001",
        request=CompetitiveIntelRequest(company="ACME"),
        agent_profiles={
            "analyst": AgentProfile(
                agent="analyst",
                max_rounds=3,
                allowed_tools=["web_search"],
            )
        },
    )
    call = make_tool_call("tc_analyst", "web_search", requested_by="analyst")

    result = runtime.execute("analyst", call, context=context)

    assert result.ok is False
    assert "not allowed" in result.error.lower()


def test_reject_unregistered_tool() -> None:
    """Calling a tool not registered in the runtime should fail."""
    runtime = ToolRuntime()
    call = make_tool_call("tc_004", "nonexistent_tool")

    result = runtime.execute("collector", call)

    assert result.ok is False
    assert result.error is not None


def test_preview_is_truncated() -> None:
    """ToolResult.preview should be a short human-readable summary of the result."""
    runtime = ToolRuntime()
    runtime.register(FakeWebSearch())
    call = make_tool_call("tc_005", "web_search", {"query": "test"})

    result = runtime.execute("collector", call)

    assert len(result.preview) > 0
    # preview should be short — not the full data dump
    assert len(result.preview) < 500


# ── Signatures ───────────────────────────────────────────────────

def test_signature_stable_for_identical_calls() -> None:
    """Same tool name + args must produce the same signature (for circuit breaker)."""
    runtime = ToolRuntime()
    call_a = make_tool_call("tc_a", "web_search", {"query": "ACME"})
    call_b = make_tool_call("tc_b", "web_search", {"query": "ACME"})

    assert runtime.signature(call_a) == runtime.signature(call_b)


def test_signature_differs_for_different_args() -> None:
    """Different args must produce different signatures."""
    runtime = ToolRuntime()
    call_a = make_tool_call("tc_a", "web_search", {"query": "ACME"})
    call_b = make_tool_call("tc_b", "web_search", {"query": "WidgetCorp"})

    assert runtime.signature(call_a) != runtime.signature(call_b)


def test_signature_differs_for_different_tool_names() -> None:
    """Different tool names with same args must produce different signatures."""
    runtime = ToolRuntime()
    call_a = make_tool_call("tc_a", "web_search", {"url": "https://x.com"})
    call_b = make_tool_call("tc_b", "web_fetch", {"url": "https://x.com"})

    assert runtime.signature(call_a) != runtime.signature(call_b)


def test_signature_stable_regardless_of_id() -> None:
    """Signature must not depend on the call's id field — only name + args."""
    runtime = ToolRuntime()
    call_a = make_tool_call("tc_aaa", "web_search", {"query": "ACME"})
    call_b = make_tool_call("tc_bbb", "web_search", {"query": "ACME"})

    assert runtime.signature(call_a) == runtime.signature(call_b)
