# 16 Terminal Dashboard

## Goal

Display per-run observability from journal events and stores.

## Scope

In scope:

- Run status.
- Agent rounds.
- Tool call counts.
- Health signals.
- Source and claim counts.
- Reviewer rework count.
- Latest active report id.
- Empty-run handling.
- Human-readable terminal rendering.

Out of scope:

- Web UI.
- Real-time streaming.
- Historical analytics.
- Mutating artifacts or journal events.
- Calling agents, tools, or the orchestrator.

## Inputs

- `JournalStore`
- `ArtifactStore`
- `run_id`

## Public Interface

```python
@dataclass(frozen=True)
class DashboardSnapshot:
    run_id: str
    status: str
    agent_rounds: dict[AgentName, int] = field(default_factory=dict)
    tool_call_count: int = 0
    source_count: int = 0
    claim_count: int = 0
    report_id: str | None = None
    review_feedback_count: int = 0
    health_signals: list[str] = field(default_factory=list)

def build_dashboard_snapshot(
    journal: JournalStore,
    artifacts: ArtifactStore,
    run_id: str,
) -> DashboardSnapshot: ...

def render_dashboard(snapshot: DashboardSnapshot) -> str: ...
```

`build_dashboard_snapshot()` is the data layer. `render_dashboard()` is the
terminal formatting layer. Keeping them separate makes the summary testable and
lets future CLI/Web adapters reuse the snapshot.

## Status Rules v0

| Events | Dashboard Status |
|---|---|
| no events | `empty` |
| any event decision is `abort` | `aborted` |
| any event decision is `rework` | `needs_rework` |
| final event decision is `stop` | `completed` |
| otherwise | final event decision |

Dashboard status is an observability summary, not a new workflow decision.

## Read-Only Boundary

Dashboard must read from stores only:

- `journal.list_run_events(run_id)`
- `artifacts.list_sources(run_id)`
- `artifacts.list_claims(run_id)`
- `artifacts.get_latest_report(run_id)`

It must not call agents, tools, the harness, or the orchestrator.

## Tests

- Summarizes rounds by agent.
- Counts tool calls.
- Shows abort and rework states.
- Handles empty runs.
- Counts source and claim artifacts.
- Renders a compact terminal summary.
- Does not depend on agent internals.

## Done Criteria

- A completed run can be inspected in the terminal.
- Dashboard reads from stores, not from agent internals.
- Empty, aborted, rework, and completed runs have explicit statuses.
- Snapshot output is structured enough for future CLI/Web reuse.
