# 13 Orchestrator

## Goal

Create the run plan and execute the default multi-agent DAG through the harness.

The orchestrator is the domain workflow controller. It should not simply call
subagents; it must wire stores, profiles, role boundaries, and artifact flow so
the run remains auditable.

## Scope

In scope:

- Create `RunContext`.
- Load agent profiles.
- Execute default DAG.
- Pass shared stores to agents.
- Pass only each agent's allowed repository/tool/model capabilities.
- Stop on approval or abort.
- Preserve the artifact sequence: sources -> claims -> report -> review.
- Keep orchestration logic outside the CLI.

Out of scope:

- Dynamic DAG optimization.
- Multi-run scheduling.
- Web UI.
- CLI parsing.

## Default DAG

```text
Collector -> Analyst -> Writer -> Reviewer
```

Each stage consumes only the artifacts from previous stages:

- Collector writes `SourceArtifact`.
- Analyst reads active sources and writes `AnalysisClaim`.
- Writer reads active claims and source metadata, then writes `ReportDraft`.
- Reviewer reads report, claims, and sources, then writes approval or `ReviewFeedback`.

## Differentiation Rules

- Orchestrator must not collapse stages into one all-powerful agent.
- Orchestrator must not pass raw collector transcripts to Writer.
- Orchestrator must create one `RunContext` with explicit `AgentProfile` budgets and tool grants.
- Orchestrator should treat `RuntimeHarness` decisions as workflow control signals, not console logs.
- A run is successful only if the final report is approved or has no blocking reviewer feedback.

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
- Verifies artifact flow order: sources before claims, claims before report, report before review.
- Ensures CLI can call orchestrator without duplicating pipeline logic.

## Done Criteria

- The orchestrator can run a full fake pipeline end to end.
- The CLI can call the orchestrator without duplicating orchestration logic.
- Real agents can be added without changing orchestrator control flow.
- The pipeline can explain which artifacts each stage consumed and produced.
