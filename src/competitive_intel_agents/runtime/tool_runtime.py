"""Tool runtime — standardized tool execution and repeat-detection signatures."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from competitive_intel_agents.agents.base import ensure_tool_allowed
from competitive_intel_agents.models import AgentName, ToolCall, ToolResult


class Tool(Protocol):
    """Minimal tool contract."""

    name: str

    def run(self, args: dict) -> dict:
        ...


class FakeWebSearch:
    """Deterministic fake search tool for tests."""

    name = "web_search"

    def run(self, args: dict) -> dict:
        query = args.get("query", "")
        return {
            "results": [
                {
                    "title": f"Search result for: {query}",
                    "url": f"https://example.com/search?q={query.replace(' ', '+')}",
                    "snippet": f"Information about {query} from public sources.",
                },
                {
                    "title": f"Analysis: {query}",
                    "url": "https://example.com/analysis",
                    "snippet": f"Recent developments regarding {query}.",
                },
            ],
            "query": query,
            "total_results": 2,
        }


class FakeWebFetch:
    """Deterministic fake page-fetch tool for tests."""

    name = "web_fetch"

    def run(self, args: dict) -> dict:
        url = args.get("url", "")
        return {
            "content": f"Content fetched from {url}. This is deterministic fake output.",
            "title": f"Page: {url}",
            "url": url,
        }


class ToolRuntime:
    """Executes tool calls with permission checks and generates stable signatures."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def execute(self, agent: AgentName, call: ToolCall) -> ToolResult:
        # Permission check
        try:
            ensure_tool_allowed(agent, call.name)
        except ValueError as exc:
            return ToolResult(
                tool_call_id=call.id,
                ok=False,
                error=str(exc),
                preview=f"Tool {call.name} not allowed for {agent}",
            )

        # Tool lookup
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                tool_call_id=call.id,
                ok=False,
                error=f"unknown tool: {call.name}",
                preview=f"Unknown tool: {call.name}",
            )

        # Execution
        try:
            data = tool.run(call.args)
            preview = self._make_preview(call.name, data)
            return ToolResult(
                tool_call_id=call.id,
                ok=True,
                data=data,
                preview=preview,
            )
        except Exception as exc:
            return ToolResult(
                tool_call_id=call.id,
                ok=False,
                data={},
                error=str(exc),
                preview=f"Tool {call.name} failed: {exc}",
            )

    def signature(self, call: ToolCall) -> str:
        """Generate a stable, deterministic signature for a tool call.

        Only based on tool name and args — not on call id or timestamp.
        Used by the harness circuit breaker to detect repeated identical calls.
        """
        payload = json.dumps(
            {"name": call.name, "args": call.args}, sort_keys=True
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _make_preview(tool_name: str, data: dict) -> str:
        """Create a short human-readable preview of tool output."""
        if tool_name == "web_search":
            count = len(data.get("results", []))
            query = data.get("query", "")
            return f"web_search '{query}' → {count} results"
        if tool_name == "web_fetch":
            url = data.get("url", "")
            title = data.get("title", "")
            return f"web_fetch '{url}' → {title}"
        # Generic fallback
        return json.dumps(data, sort_keys=True)[:200]
