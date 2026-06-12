"""Tests for ConversationStore and build_with_history."""

import pytest

from competitive_intel_agents.memory import (
    ConversationStore,
    InMemoryConversationStore,
)
from competitive_intel_agents.prompts import AgentPromptLibrary


# ── InMemoryConversationStore ───────────────────────────────────


def test_empty_history_returns_empty_list() -> None:
    store = InMemoryConversationStore()
    assert store.get_history("run_1", "analyst") == []


def test_append_and_get_history() -> None:
    store = InMemoryConversationStore()
    store.append_exchange("run_1", "analyst", "analyze sources", '{"claims": []}')
    history = store.get_history("run_1", "analyst")
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "analyze sources"}
    assert history[1] == {"role": "assistant", "content": '{"claims": []}'}


def test_multiple_exchanges() -> None:
    store = InMemoryConversationStore()
    store.append_exchange("run_1", "analyst", "task 1", "result 1")
    store.append_exchange("run_1", "analyst", "task 2", "result 2")
    history = store.get_history("run_1", "analyst")
    assert len(history) == 4
    assert history[2] == {"role": "user", "content": "task 2"}
    assert history[3] == {"role": "assistant", "content": "result 2"}


def test_different_agents_isolated() -> None:
    store = InMemoryConversationStore()
    store.append_exchange("run_1", "analyst", "a_task", "a_result")
    store.append_exchange("run_1", "writer", "w_task", "w_result")
    analyst_history = store.get_history("run_1", "analyst")
    writer_history = store.get_history("run_1", "writer")
    assert len(analyst_history) == 2
    assert len(writer_history) == 2
    assert analyst_history[0]["content"] == "a_task"
    assert writer_history[0]["content"] == "w_task"


def test_different_runs_isolated() -> None:
    store = InMemoryConversationStore()
    store.append_exchange("run_1", "analyst", "r1", "res1")
    store.append_exchange("run_2", "analyst", "r2", "res2")
    assert store.get_history("run_1", "analyst")[0]["content"] == "r1"
    assert store.get_history("run_2", "analyst")[0]["content"] == "r2"


def test_clear_removes_history() -> None:
    store = InMemoryConversationStore()
    store.append_exchange("run_1", "analyst", "task", "result")
    store.clear("run_1", "analyst")
    assert store.get_history("run_1", "analyst") == []


def test_clear_nonexistent_is_noop() -> None:
    store = InMemoryConversationStore()
    store.clear("run_1", "analyst")  # should not raise


def test_truncation_removes_oldest_turns() -> None:
    store = InMemoryConversationStore(max_history_turns=2)
    store.append_exchange("r", "a", "t1", "r1")
    store.append_exchange("r", "a", "t2", "r2")
    store.append_exchange("r", "a", "t3", "r3")  # oldest should be truncated
    history = store.get_history("r", "a")
    # max_history_turns=2 → max 4 messages
    assert len(history) == 4
    assert history[0]["content"] == "t2"
    assert history[1]["content"] == "r2"
    assert history[2]["content"] == "t3"
    assert history[3]["content"] == "r3"


def test_get_history_returns_copy() -> None:
    store = InMemoryConversationStore()
    store.append_exchange("r", "a", "task", "result")
    history = store.get_history("r", "a")
    history.append({"role": "user", "content": "extra"})
    assert len(store.get_history("r", "a")) == 2


# ── build_with_history ──────────────────────────────────────────


def test_build_with_history_no_history_matches_build() -> None:
    lib = AgentPromptLibrary()
    task = "Analyze these sources"
    context = {"company": "TestCorp"}

    normal = lib.build("analyst", task, context)
    with_history = lib.build_with_history("analyst", task, context, history=None)

    assert normal.messages == with_history.messages


def test_build_with_history_includes_history() -> None:
    lib = AgentPromptLibrary()
    history = [
        {"role": "user", "content": "first task"},
        {"role": "assistant", "content": '{"claims": []}'},
    ]
    req = lib.build_with_history("analyst", "analyze again", {"company": "X"}, history=history)

    # system + 2 history + 1 new user = 4 messages
    assert len(req.messages) == 4
    assert req.messages[0]["role"] == "system"
    assert req.messages[1]["content"] == "first task"
    assert req.messages[2]["content"] == '{"claims": []}'
    assert "analyze again" in req.messages[3]["content"]


def test_build_with_history_strips_system_from_history() -> None:
    lib = AgentPromptLibrary()
    history = [
        {"role": "system", "content": "old system prompt"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "result"},
    ]
    req = lib.build_with_history("analyst", "new task", {}, history=history)

    system_messages = [m for m in req.messages if m["role"] == "system"]
    assert len(system_messages) == 1
    assert "old system prompt" not in system_messages[0]["content"]


def test_build_with_history_empty_history_same_as_none() -> None:
    lib = AgentPromptLibrary()
    task = "test"
    context = {"company": "X"}

    with_empty = lib.build_with_history("analyst", task, context, history=[])
    with_none = lib.build_with_history("analyst", task, context, history=None)

    assert with_empty.messages == with_none.messages


# ── InMemoryArtifactStore agent_contexts ────────────────────────


def test_agent_context_save_and_get() -> None:
    from competitive_intel_agents.artifacts import InMemoryArtifactStore

    store = InMemoryArtifactStore()
    store.save_agent_context("run_1", "analyst", "writer", {"strategy": "broad"})
    contexts = store.get_agent_contexts("run_1", "writer")
    assert len(contexts) == 1
    assert contexts[0]["from_agent"] == "analyst"
    assert contexts[0]["strategy"] == "broad"


def test_agent_context_multiple_agents() -> None:
    from competitive_intel_agents.artifacts import InMemoryArtifactStore

    store = InMemoryArtifactStore()
    store.save_agent_context("run_1", "analyst", "reviewer", {"assessed": 5})
    store.save_agent_context("run_1", "writer", "reviewer", {"sections": 4})
    contexts = store.get_agent_contexts("run_1", "reviewer")
    assert len(contexts) == 2
    agents = {c["from_agent"] for c in contexts}
    assert agents == {"analyst", "writer"}


def test_agent_context_different_targets_isolated() -> None:
    from competitive_intel_agents.artifacts import InMemoryArtifactStore

    store = InMemoryArtifactStore()
    store.save_agent_context("run_1", "analyst", "writer", {"for_writer": True})
    store.save_agent_context("run_1", "analyst", "reviewer", {"for_reviewer": True})
    assert len(store.get_agent_contexts("run_1", "writer")) == 1
    assert len(store.get_agent_contexts("run_1", "reviewer")) == 1


def test_agent_context_no_data_returns_empty() -> None:
    from competitive_intel_agents.artifacts import InMemoryArtifactStore

    store = InMemoryArtifactStore()
    assert store.get_agent_contexts("run_1", "writer") == []
