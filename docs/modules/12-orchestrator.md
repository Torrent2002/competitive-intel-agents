# 12 Orchestrator

## Goal

Create the run plan and execute the default multi-agent DAG through the harness.

## Scope

In scope:

- Create `RunContext`.
- Load agent profiles.
- Execute default DAG.
- Pass shared stores to agents.
- Stop on approval or abort.

Out of scope:

- Dynamic DAG optimization.
- Multi-run scheduling.
- Web UI.

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

- One command can run a full fake pipeline end to end.
- Real agents can be added without changing orchestrator control flow.

