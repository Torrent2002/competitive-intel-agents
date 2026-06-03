# 06 Tool Runtime

## Goal

Standardize tool execution and tool call recording.

## Scope

In scope:

- Tool interface.
- Tool call result object.
- Tool allowlist per agent.
- Tool call signature used by circuit breaker.

Out of scope:

- Full browser automation.
- Paid search API integration.
- Scraping policy engine.

## Public Interface

```python
class Tool:
    name: str
    def run(self, args: dict) -> dict: ...

class ToolRuntime:
    def execute(self, agent: AgentName, call: ToolCall) -> ToolResult: ...
    def signature(self, call: ToolCall) -> str: ...
```

## Allowlist Rules

- Tool permissions come from `AgentProfile.allowed_tools`.
- Collector may use `web_search` and `web_fetch`.
- Analyst, Writer, and Reviewer use no web tools in v0.
- Disallowed tool attempts should return a failed `ToolResult`; they should not call the underlying tool.

## Initial Tools

- `web_search`
- `web_fetch`

For early tests, these can be fake deterministic tools.

## Tests

- Execute an allowed tool.
- Reject a disallowed tool.
- Generate stable signatures for identical calls.
- Generate different signatures for different args.

## Done Criteria

- Collector can call search/fetch through the runtime.
- Harness can inspect tool calls without knowing tool internals.
