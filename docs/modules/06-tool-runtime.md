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

class ToolPolicy:
    def allowed_tools(self, agent: AgentName, context: RunContext | None = None) -> frozenset[str]: ...
    def ensure_allowed(self, agent: AgentName, call: ToolCall, context: RunContext | None = None) -> None: ...

class ToolRuntime:
    def execute(
        self,
        agent: AgentName,
        call: ToolCall,
        context: RunContext | None = None,
    ) -> ToolResult: ...
    def signature(self, call: ToolCall) -> str: ...
```

## Allowlist Rules

- Role permissions from `AGENT_ACCESS_MATRIX` are the maximum capability ceiling.
- Effective permissions come from `ToolPolicy`.
- If no `RunContext` is provided, `ToolPolicy` uses the role ceiling.
- If a `RunContext` is provided, `ToolPolicy` intersects the role ceiling with `AgentProfile.allowed_tools`.
- Collector may use `web_search` and `web_fetch` only when those tools are also allowed by the run profile.
- Analyst, Writer, and Reviewer use no web tools in v0, even if a profile tries to grant them.
- `ToolCall.requested_by` must match the executing agent. Mismatches return a failed `ToolResult` and must not call the underlying tool.
- Disallowed tool attempts should return a failed `ToolResult`; they should not call the underlying tool.

## Initial Tools

- `web_search`
- `web_fetch`

For early tests, these can be fake deterministic tools.

## Tests

- Execute an allowed tool.
- Reject a disallowed tool.
- Reject a tool call whose `requested_by` does not match the executing agent.
- Verify run profiles can narrow Collector's default tool permissions.
- Verify run profiles cannot grant Analyst tools outside the role ceiling.
- Generate stable signatures for identical calls.
- Generate different signatures for different args.

## Done Criteria

- Collector can call search/fetch through the runtime.
- Harness can inspect tool calls without knowing tool internals.
- Harness can pass `RunContext` to enforce per-run tool grants without coupling to the access matrix.
