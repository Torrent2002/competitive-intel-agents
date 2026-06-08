# 19 Dashboard CLI Command

## Goal

Expose terminal dashboard rendering as a direct CLI command.

## Why It Matters

Module 16 implemented dashboard snapshot/rendering, but the user cannot invoke it
directly yet. README says "Per-run dashboard (terminal or basic web)", so the
terminal path needs a real command.

## Scope

In scope:

- `competitive-intel dashboard --run-id <id>` command.
- Optional `--workspace <path>` for persisted runs.
- `competitive-intel run --show-dashboard` convenience flag.
- Render run status, agent rounds, tool calls, sources, claims, report id,
  reviewer feedback count, and signals.

Out of scope:

- Web dashboard.
- Historical analytics.
- Live streaming.

## Dependencies

- Module 16 Terminal Dashboard.
- Module 20 Persistent Local Workspace for cross-process run lookup.

## Public Interface

```text
competitive-intel run \
  --input tests/fixtures/request.json \
  --workspace .competitive-intel \
  --show-dashboard

competitive-intel dashboard \
  --run-id run_xxx \
  --workspace .competitive-intel
```

`run --show-dashboard` renders the dashboard from the in-process stores after
the run. `dashboard --run-id` reads persisted stores from workspace.

## Tests

- `run --show-dashboard` prints dashboard after completion.
- `dashboard --run-id` renders stored run after process restart.
- Empty run id prints a readable error.
- Command does not call agents or mutate stores.
- Dashboard command works in a second process after the original run exits.

## Done Criteria

- Terminal dashboard is directly usable from CLI.
- Dashboard output comes from stores, not from in-memory agent internals.
