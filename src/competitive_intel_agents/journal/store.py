"""Append-only journal stores for round events."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol

from competitive_intel_agents.models import AgentName, RoundEvent


class DuplicateJournalEventError(ValueError):
    """Raised when appending an event id that already exists."""


class JournalStore(Protocol):
    """Storage contract used by the harness and dashboard."""

    def append(self, event: RoundEvent) -> None:
        ...

    def list_run_events(self, run_id: str) -> list[RoundEvent]:
        ...

    def list_agent_events(self, run_id: str, agent: AgentName) -> list[RoundEvent]:
        ...


class InMemoryJournalStore:
    """Simple append-only journal store for tests and local runs."""

    def __init__(self) -> None:
        self._events: list[RoundEvent] = []
        self._event_ids: set[str] = set()

    def append(self, event: RoundEvent) -> None:
        if event.id in self._event_ids:
            raise DuplicateJournalEventError(f"duplicate journal event id: {event.id}")
        self._events.append(event)
        self._event_ids.add(event.id)

    def list_run_events(self, run_id: str) -> list[RoundEvent]:
        return [event for event in self._events if event.run_id == run_id]

    def list_agent_events(self, run_id: str, agent: AgentName) -> list[RoundEvent]:
        return [
            event
            for event in self._events
            if event.run_id == run_id and event.agent == agent
        ]


class SQLiteJournalStore:
    """SQLite-backed append-only journal store."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS journal_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                run_id TEXT NOT NULL,
                agent TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def append(self, event: RoundEvent) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO journal_events (id, run_id, agent, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.run_id,
                    event.agent,
                    json.dumps(event.to_dict(), sort_keys=True),
                ),
            )
            self._connection.commit()
        except sqlite3.IntegrityError as error:
            raise DuplicateJournalEventError(
                f"duplicate journal event id: {event.id}"
            ) from error

    def list_run_events(self, run_id: str) -> list[RoundEvent]:
        rows = self._connection.execute(
            """
            SELECT payload FROM journal_events
            WHERE run_id = ?
            ORDER BY sequence ASC
            """,
            (run_id,),
        ).fetchall()
        return [self._event_from_payload(row[0]) for row in rows]

    def list_agent_events(self, run_id: str, agent: AgentName) -> list[RoundEvent]:
        rows = self._connection.execute(
            """
            SELECT payload FROM journal_events
            WHERE run_id = ? AND agent = ?
            ORDER BY sequence ASC
            """,
            (run_id, agent),
        ).fetchall()
        return [self._event_from_payload(row[0]) for row in rows]

    @staticmethod
    def _event_from_payload(payload: str) -> RoundEvent:
        return RoundEvent.from_dict(json.loads(payload))
