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
- Return `needs_rework` with reviewer feedback when the reviewer emits fixable feedback.
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

Constructor dependencies are injectable so tests and future production adapters can
replace stores, harness, and run id generation without changing control flow:

```python
Orchestrator(
    artifacts: ArtifactStore | None = None,
    journal: JournalStore | None = None,
    harness: Harness | None = None,
    agent_profiles: dict[str, AgentProfile] | None = None,
    run_id_factory: Callable[[], str] | None = None,
)
```

Default local runtime:

- `InMemoryArtifactStore`
- `InMemoryJournalStore`
- `RuntimeHarness`
- `InMemoryCheckpointStore`
- `ToolRuntime` with deterministic `FakeWebSearch` and `FakeWebFetch`
- profiles loaded from `config/agent_profiles.yaml`

## Run Status v0

| Status | Meaning |
|---|---|
| `approved` | Reviewer stopped with approval and no blocking feedback. |
| `needs_rework` | Reviewer returned structured feedback and harness returned `rework`. |
| `aborted` | A non-recoverable harness abort happened before approval. |

The orchestrator does not decide how to fix `needs_rework`; module 15 owns the
bounded rework loop.

## Control Flow

```text
create RunContext
  -> Collector through RuntimeHarness
  -> Analyst through RuntimeHarness
  -> Writer through RuntimeHarness
  -> Reviewer through RuntimeHarness
  -> RunResult
```

The orchestrator treats `AgentResult.decision` as the control signal:

- `stop`: move to the next stage.
- `rework`: stop the current run and return reviewer feedback.
- `abort`: stop the current run and return an aborted status.

It does not pass raw collector transcripts to downstream agents. Downstream
agents only read structured artifacts from the shared artifact store.

## Tests

- Runs agents in the expected order.
- Stops when reviewer approves.
- Aborts when harness aborts.
- Returns `needs_rework` with structured reviewer feedback.
- Records run-level status.
- Verifies artifact flow order: sources before claims, claims before report, report before review.
- Ensures CLI can call orchestrator without duplicating pipeline logic.
- Creates `RunContext` with role-bounded `AgentProfile` grants.

## Done Criteria

- The orchestrator can run a full fake pipeline end to end.
- The CLI can call the orchestrator without duplicating orchestration logic.
- Real agents can be added without changing orchestrator control flow.
- The pipeline can explain which artifacts each stage consumed and produced.
- Reviewer feedback can reach `RunResult` without parsing natural-language messages.
