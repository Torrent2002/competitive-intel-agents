# 08 Runtime Harness

## Goal

Wrap every agent round with reliability and observability controls.

## Scope

In scope:

- `pre_round` checks.
- Agent round execution.
- `post_round` journaling.
- Round budget enforcement.
- Repeated tool call circuit breaker.
- Lightweight checkpoint hook.
- Harness decision output.
- Passing run context into tool execution so per-run permissions are enforced.
- Preserving tool-call provenance in journal events.
- Passing prior tool results into the next round through `AgentState.memory`.

Out of scope:

- Advanced semantic hallucination detection.
- Complex retry backoff.
- Production checkpoint recovery.

## Public Interface

```python
class CheckpointStore:
    def save(self, checkpoint: Checkpoint) -> None: ...
    def list_checkpoints(self, run_id: str, agent: AgentName) -> list[Checkpoint]: ...

class RuntimeHarness:
    def __init__(
        self,
        journal: JournalStore,
        tool_runtime: ToolRuntime,
        checkpoints: CheckpointStore | None = None,
        repeated_tool_limit: int = 3,
    ) -> None: ...
    def run_agent(self, context: RunContext, agent: Agent) -> AgentResult: ...
    def run_round(
        self,
        context: RunContext,
        agent: Agent,
        round_index: int,
        is_budget_final_round: bool = False,
        state_memory: dict[str, object] | None = None,
    ) -> RoundEvent: ...
```

`InMemoryCheckpointStore` is the v0 checkpoint implementation for tests and
local runs. Production recovery is intentionally out of scope.

## Decision Rules v0

| Condition | Decision |
|---|---|
| Agent returns completed result | `stop` |
| Round budget exceeded | `abort` |
| Identical tool call repeats 3 times | `abort` |
| Transient tool or model error | `retry` |
| Reviewer returns fixable feedback | `rework` |
| New artifact or progress signal appears | `continue` |

Decision precedence:

1. `completed=True` returns `stop`.
2. Repeated identical tool call at the configured limit returns `abort`.
3. Tool/runtime errors return `retry`.
4. Final budget round with no terminal condition returns `abort`.
5. Otherwise return `continue`.

`run_agent()` loops from round `1` through `AgentProfile.max_rounds`. If no
profile exists for the agent, the fallback budget is one round.

## Permission and Provenance Rules

- Harness is the only component that executes tool calls returned by agents.
- For each `ToolCall`, harness must pass the currently running agent name and `RunContext` into `ToolRuntime.execute(agent, call, context)`.
- If `call.requested_by` does not match the currently running agent, the failed `ToolResult` should be treated as an agent/runtime error and journaled.
- Tool signatures are computed from tool name and args for repeated-call detection, but provenance still records `requested_by`.
- Harness should not import or reimplement `AGENT_ACCESS_MATRIX`; effective authorization belongs to `ToolPolicy` through `ToolRuntime`.
- Harness stores the computed signature back on the `ToolCall` before journaling the round event.
- Repeated tool call counts are isolated by `run_id` and agent. Reusing one harness instance across runs must not leak circuit breaker state.
- Failed tool executions are represented in event `signals` as `tool_error:<tool_call_id>` in v0. Full `ToolResult` journaling can be added later if the `RoundEvent` model grows a tool result field.
- Tool results are converted to dictionaries and written to `state_memory["tool_results"]` for the next round when `run_agent()` owns the loop.

## Agent Memory Rules

- `run_agent()` maintains a mutable per-agent memory dictionary across rounds.
- Each `run_round()` receives a copy of that memory in `AgentState.memory`.
- After tool execution, successful and failed `ToolResult` objects are serialized into `memory["tool_results"]` for the next round.
- Agents can use prior tool results without directly depending on `ToolRuntime`.
- Direct callers of `run_round()` may pass `state_memory` when they want this same memory behavior.

## Artifact Rules

- Harness and rework code must write new artifact ids for revised work.
- Harness must not save an artifact id twice.
- Rework should call `mark_superseded(old_id, replacement_id)` only after the replacement artifact has been saved and lineage validation can pass.
- Journal events should keep `output_artifact_ids` stable even if those artifacts later become `superseded` or `rejected`.

## Journal and Checkpoint Rules

- Each round appends exactly one `RoundEvent`.
- v0 event ids are deterministic: `{run_id}:{agent}:{round_index}`.
- A checkpoint is saved after each round when a checkpoint store is configured.
- v0 checkpoint state records the round index and agent signals only. Full state recovery is a later module.

## Tests

- Stops on agent completion.
- Aborts after budget exhaustion.
- Aborts after repeated identical tool calls.
- Appends one journal event per round.
- Saves checkpoint after successful round.
- Saves checkpoint after retry and abort rounds when a checkpoint store is configured.
- Uses stable `ToolCall` signatures for repeated-call checks.
- Keeps repeated-call counts isolated by run id.
- Passes `RunContext` to tool execution so `AgentProfile.allowed_tools` is honored.
- Passes tool results to the next round through `AgentState.memory`.
- Journals failed tool results caused by permission or provenance errors.
- Does not overwrite artifacts during rework.

## Done Criteria

- Fake agents can be run through the harness.
- Harness output is deterministic in tests.
- Journal events include decision and signals.
- Tool execution honors both role ceilings and run-specific profile grants.
