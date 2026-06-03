# 14 Terminal Dashboard

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

Out of scope:

- Web UI.
- Real-time streaming.
- Historical analytics.

## Inputs

- `JournalStore`
- `ArtifactStore`
- `run_id`

## Tests

- Summarizes rounds by agent.
- Counts tool calls.
- Shows abort and rework states.
- Handles empty runs.

## Done Criteria

- A completed run can be inspected in the terminal.
- Dashboard reads from stores, not from agent internals.

