# 03 Agent Interface

## Goal

Define the minimal contract every agent must implement.

## Scope

In scope:

- Agent name.
- Agent profile.
- Round input.
- Round output.
- Progress signals.
- Agent data access boundaries.

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

## Data Access Matrix

Agents should receive narrow repository/tool/model capabilities instead of unrestricted shared state.

| Agent | May Read | May Write | May Use Tools |
|---|---|---|---|
| Collector | Run request, prior collector sources | Source artifacts | `web_search`, `web_fetch` |
| Analyst | Active source artifacts, reviewer feedback for analyst | Analysis claims | none |
| Writer | Active analysis claims, active source metadata, reviewer feedback for writer | Report drafts | none |
| Reviewer | Active report draft, active claims, active sources | Review feedback | none |

Rules:

- Agents do not write journal events directly. The harness owns journaling.
- Writer should not read raw fetched pages directly; it should consume claims and source metadata.
- Analyst should not call web tools; missing evidence should become reviewer feedback routed to Collector.
- Reviewer should not mutate artifacts; it only approves or returns feedback.

## Tests

- Fake agent can complete.
- Fake agent can request tool calls.
- Fake agent can emit output artifact ids.
- Agent access boundaries are represented by test doubles or narrow interfaces.

## Done Criteria

- Harness can run any conforming agent.
- Agent implementations do not write journal events directly.
