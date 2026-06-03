# 13 Orchestrator

## Goal

Create the run plan and execute the default multi-agent DAG through the harness.

## Scope

In scope:

- Create `RunContext`.
- Load agent profiles.
- Execute default DAG.
- Pass shared stores to agents.
- Pass only each agent's allowed repository/tool/model capabilities.
- Stop on approval or abort.

Out of scope:

- Dynamic DAG optimization.
- Multi-run scheduling.
- Web UI.
- CLI parsing.

## Default DAG

```text
Collector -> Analyst -> Writer -> Reviewer
```

## Public Interface

```python
class Orchestrator:
    def run(self, request: CompetitiveIntelRequest) -> RunResult: ...
```

## Tests

- Runs agents in the expected order.
- Stops when reviewer approves.
- Aborts when harness aborts.
- Records run-level status.

## Done Criteria

- The orchestrator can run a full fake pipeline end to end.
- The CLI can call the orchestrator without duplicating orchestration logic.
- Real agents can be added without changing orchestrator control flow.
