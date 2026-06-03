# Spec Coding Plan

This document breaks the project into small implementation modules. Each module should be implemented through a focused spec before coding.

The intended development style is:

1. Pick one module.
2. Write or refine its spec.
3. Implement only that module's public contract.
4. Add focused tests.
5. Move to the next module.

## Module Sequence

| Order | Module | Why It Comes Here |
|---|---|---|
| 1 | Project Skeleton | Creates the package, config, and test layout |
| 2 | Core Models | Defines shared data contracts before behavior |
| 3 | Agent Interface | Defines the minimal agent contract used by the harness |
| 4 | Journal Store | Makes every later module observable |
| 5 | Artifact Store | Gives agents a structured shared memory |
| 6 | Tool Runtime | Standardizes tool calls and repeated-call detection |
| 7 | Model Runtime | Standardizes model calls and fake model tests |
| 8 | Runtime Harness v0 | Wraps agent rounds with budget, signals, and decisions |
| 9 | Collector Agent v0 | Produces source artifacts |
| 10 | Analyst Agent v0 | Produces sourced analysis claims |
| 11 | Writer Agent v0 | Produces a structured report draft |
| 12 | Reviewer Agent v0 | Checks source coverage and returns structured feedback |
| 13 | Orchestrator v0 | Runs the default four-agent DAG |
| 14 | CLI Entrypoint | Provides one command for fake and local runs |
| 15 | Rework Loop v0 | Routes reviewer feedback back to the responsible agent |
| 16 | Terminal Dashboard v0 | Shows run status from journal events |
| 17 | Golden Replay v0 | Catches schema and quality regressions |

## Recommended Milestones

### Milestone 1: Observable Single Run

Goal: one run can execute through the harness and leave a replayable event trail.

Includes:

- Project Skeleton
- Core Models
- Agent Interface
- Journal Store
- Runtime Harness v0

Done when:

- A fake agent can run for multiple rounds.
- Each round writes a journal event.
- Round budget is enforced.
- Unit tests cover harness decisions.

### Milestone 2: Structured Competitive Report

Goal: the pipeline creates a report draft from structured artifacts.

Includes:

- Artifact Store
- Tool Runtime
- Model Runtime
- Collector Agent v0
- Analyst Agent v0
- Writer Agent v0
- Orchestrator v0
- CLI Entrypoint

Done when:

- A sample input produces source artifacts, analysis claims, and a report draft.
- The final report includes source references.
- Orchestrator can run the default DAG end to end.
- `tests/fixtures/` contains a fake request and expected artifact/report shape.
- `competitive-intel run --input tests/fixtures/request.json` can run the fake pipeline.

### Milestone 3: Quality and Rework

Goal: reviewer feedback can reject and route fixable issues.

Includes:

- Reviewer Agent v0
- Rework Loop v0

Done when:

- Unsupported claims are rejected.
- Review feedback has a target agent and artifact id.
- Rework attempts are capped.

### Milestone 4: Regression and Observability

Goal: runs can be inspected and compared over time.

Includes:

- Terminal Dashboard v0
- Golden Replay v0

Done when:

- A terminal view summarizes rounds, tool calls, sources, claims, and health.
- Golden cases compare schema expectations, source coverage, reviewer rejections, and cost counters.

## Module Documents

- [01 Project Skeleton](modules/01-project-skeleton.md)
- [02 Core Models](modules/02-core-models.md)
- [03 Agent Interface](modules/03-agent-interface.md)
- [04 Journal Store](modules/04-journal-store.md)
- [05 Artifact Store](modules/05-artifact-store.md)
- [06 Tool Runtime](modules/06-tool-runtime.md)
- [07 Model Runtime](modules/07-model-runtime.md)
- [08 Runtime Harness](modules/08-runtime-harness.md)
- [09 Collector Agent](modules/09-collector-agent.md)
- [10 Analyst Agent](modules/10-analyst-agent.md)
- [11 Writer Agent](modules/11-writer-agent.md)
- [12 Reviewer Agent](modules/12-reviewer-agent.md)
- [13 Orchestrator](modules/13-orchestrator.md)
- [14 CLI Entrypoint](modules/14-cli-entrypoint.md)
- [15 Rework Loop](modules/15-rework-loop.md)
- [16 Terminal Dashboard](modules/16-terminal-dashboard.md)
- [17 Golden Replay](modules/17-golden-replay.md)
