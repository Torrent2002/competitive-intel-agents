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

Out of scope:

- Advanced semantic hallucination detection.
- Complex retry backoff.
- Production checkpoint recovery.

## Public Interface

```python
class RuntimeHarness:
    def run_agent(self, context: RunContext, agent: Agent) -> AgentResult: ...
    def run_round(self, context: RunContext, agent: Agent, round_index: int) -> RoundEvent: ...
```

## Decision Rules v0

| Condition | Decision |
|---|---|
| Agent returns completed result | `stop` |
| Round budget exceeded | `abort` |
| Identical tool call repeats 3 times | `abort` |
| Transient tool or model error | `retry` |
| Reviewer returns fixable feedback | `rework` |
| New artifact or progress signal appears | `continue` |

## Tests

- Stops on agent completion.
- Aborts after budget exhaustion.
- Aborts after repeated identical tool calls.
- Appends one journal event per round.
- Saves checkpoint after successful round.
- Uses stable `ToolCall` signatures for repeated-call checks.

## Done Criteria

- Fake agents can be run through the harness.
- Harness output is deterministic in tests.
- Journal events include decision and signals.
