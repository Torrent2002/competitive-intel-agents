# 04 Journal Store

## Goal

Persist append-only round events so every agent decision can be replayed.

## Scope

In scope:

- Append journal events.
- List events by `run_id`.
- List events by `run_id` and `agent`.
- Prevent duplicate event ids.

Out of scope:

- Full event sourcing replay.
- Database migrations.
- Dashboard rendering.

## Public Interface

```python
class JournalStore:
    def append(self, event: RoundEvent) -> None: ...
    def list_run_events(self, run_id: str) -> list[RoundEvent]: ...
    def list_agent_events(self, run_id: str, agent: AgentName) -> list[RoundEvent]: ...
```

## Storage Recommendation

Start with an in-memory implementation and a SQLite implementation behind the same interface.

## Tests

- Append and read events in order.
- Reject duplicate ids.
- Filter by agent.
- Preserve event JSON fields.

## Done Criteria

- Harness can depend on `JournalStore` without knowing the storage backend.
- A run's event trail can be printed or inspected in tests.
