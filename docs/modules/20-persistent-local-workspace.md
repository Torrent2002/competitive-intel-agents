# 20 Persistent Local Workspace

## Goal

Persist local runs across CLI processes so reports, artifacts, journal events,
and dashboard state can be inspected later.

## Scope

In scope:

- Workspace directory, conventionally `.competitive-intel/`.
- SQLite-backed artifact store and journal store.
- Run metadata store.
- CLI flags:
  - `--workspace .competitive-intel`
  - `--run-id <id>` where applicable
- List recent runs.
- Load a prior run for dashboard/report inspection.
- Persist run metadata in `runs.json`.

Out of scope:

- PostgreSQL.
- Multi-user auth.
- Cloud sync.

## Public Interface

```text
competitive-intel run --input request.json --workspace .competitive-intel
competitive-intel runs --workspace .competitive-intel
competitive-intel dashboard --run-id run_xxx --workspace .competitive-intel
```

Workspace layout v1a:

```text
.competitive-intel/
  artifacts.sqlite
  journal.sqlite
  runs.json
```

`LocalWorkspace` exposes:

```python
workspace.artifacts  # SQLiteArtifactStore
workspace.journal    # SQLiteJournalStore
workspace.save_run_result(result)
workspace.get_run_result(run_id)
workspace.list_run_results()
```

## Tests

- CLI run persists artifacts and journal events to workspace.
- A second process can read and render the prior run.
- Run ids are unique and listable.
- Workspace schema migration is safe for v1.
- `runs` command lists persisted run ids and statuses.

## Done Criteria

- CLI results survive process exit.
- Terminal dashboard and report viewing can work by `run_id`.
