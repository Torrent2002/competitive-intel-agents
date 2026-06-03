# 07 Agent Interface

## Goal

Define the minimal contract every agent must implement.

## Scope

In scope:

- Agent name.
- Agent profile.
- Round input.
- Round output.
- Progress signals.

Out of scope:

- Prompt templates.
- Model-specific adapters.
- Agent-specific reasoning.

## Public Interface

```python
class Agent(Protocol):
    name: AgentName

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        ...
```

## AgentRoundResult

Should include:

- `completed`
- `tool_calls`
- `output_artifact_ids`
- `signals`
- `message`
- `error`

## Tests

- Fake agent can complete.
- Fake agent can request tool calls.
- Fake agent can emit output artifact ids.

## Done Criteria

- Harness can run any conforming agent.
- Agent implementations do not write journal events directly.

