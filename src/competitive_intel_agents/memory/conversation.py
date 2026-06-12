"""Agent conversation history — multi-turn LLM memory across rounds and rework."""

from __future__ import annotations

from typing import Protocol


class ConversationStore(Protocol):
    """Storage contract for per-agent conversation history within a run."""

    def get_history(
        self, run_id: str, agent_name: str
    ) -> list[dict[str, str]]: ...

    def append_exchange(
        self,
        run_id: str,
        agent_name: str,
        user_msg: str,
        assistant_msg: str,
    ) -> None: ...

    def clear(self, run_id: str, agent_name: str) -> None: ...


class InMemoryConversationStore:
    """In-memory conversation store for single-run usage."""

    def __init__(self, max_history_turns: int = 6) -> None:
        self._max_history_turns = max_history_turns
        self._store: dict[tuple[str, str], list[dict[str, str]]] = {}

    def get_history(
        self, run_id: str, agent_name: str
    ) -> list[dict[str, str]]:
        return list(self._store.get((run_id, agent_name), []))

    def append_exchange(
        self,
        run_id: str,
        agent_name: str,
        user_msg: str,
        assistant_msg: str,
    ) -> None:
        key = (run_id, agent_name)
        history = self._store.setdefault(key, [])
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": assistant_msg})
        # Truncate oldest turns if exceeding limit.
        # Each turn = 2 messages (user + assistant).
        max_messages = self._max_history_turns * 2
        if len(history) > max_messages:
            self._store[key] = history[-max_messages:]

    def clear(self, run_id: str, agent_name: str) -> None:
        self._store.pop((run_id, agent_name), None)
