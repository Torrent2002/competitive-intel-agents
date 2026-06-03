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
| 3 | Journal Store | Makes every later module observable |
| 4 | Artifact Store | Gives agents a structured shared memory |
| 5 | Runtime Harness v0 | Wraps agent rounds with budget, signals, and decisions |
| 6 | Tool Runtime | Standardizes tool calls and repeated-call detection |
| 7 | Agent Interface | Defines the minimal agent contract |
| 8 | Collector Agent v0 | Produces source artifacts |
| 9 | Analyst Agent v0 | Produces sourced analysis claims |
| 10 | Writer Agent v0 | Produces a structured report draft |
| 11 | Reviewer Agent v0 | Checks source coverage and returns structured feedback |
| 12 | Orchestrator v0 | Runs the default four-agent DAG |
| 13 | Rework Loop v0 | Routes reviewer feedback back to the responsible agent |
| 14 | Terminal Dashboard v0 | Shows run status from journal events |
| 15 | Golden Replay v0 | Catches schema and quality regressions |

## Recommended Milestones

### Milestone 1: Observable Single Run

Goal: one run can execute through the harness and leave a replayable event trail.

Includes:

- Project Skeleton
- Core Models
- Journal Store
- Runtime Harness v0
- Agent Interface

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
- Collector Agent v0
- Analyst Agent v0
- Writer Agent v0
- Orchestrator v0

Done when:

- A sample input produces source artifacts, analysis claims, and a report draft.
- The final report includes source references.
- Orchestrator can run the default DAG end to end.

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
- [03 Journal Store](modules/03-journal-store.md)
- [04 Artifact Store](modules/04-artifact-store.md)
- [05 Runtime Harness](modules/05-runtime-harness.md)
- [06 Tool Runtime](modules/06-tool-runtime.md)
- [07 Agent Interface](modules/07-agent-interface.md)
- [08 Collector Agent](modules/08-collector-agent.md)
- [09 Analyst Agent](modules/09-analyst-agent.md)
- [10 Writer Agent](modules/10-writer-agent.md)
- [11 Reviewer Agent](modules/11-reviewer-agent.md)
- [12 Orchestrator](modules/12-orchestrator.md)
- [13 Rework Loop](modules/13-rework-loop.md)
- [14 Terminal Dashboard](modules/14-terminal-dashboard.md)
- [15 Golden Replay](modules/15-golden-replay.md)

