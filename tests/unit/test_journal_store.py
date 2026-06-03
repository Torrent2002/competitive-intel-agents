import pytest

from competitive_intel_agents.journal import (
    DuplicateJournalEventError,
    InMemoryJournalStore,
    SQLiteJournalStore,
)
from competitive_intel_agents.models import RoundEvent, ToolCall


def make_event(
    event_id: str,
    run_id: str = "run_001",
    agent: str = "collector",
    round_number: int = 1,
) -> RoundEvent:
    return RoundEvent(
        id=event_id,
        run_id=run_id,
        agent=agent,
        round=round_number,
        decision="continue",
        tool_calls=[
            ToolCall(
                id=f"tool_{event_id}",
                name="web_fetch",
                args={"url": "https://example.com"},
                requested_by="collector",
            )
        ],
        output_artifact_ids=[f"artifact_{event_id}"],
        signals=["progress"],
        timestamp=f"2026-06-03T14:22:0{round_number}Z",
    )


@pytest.mark.parametrize("store_factory", [InMemoryJournalStore, SQLiteJournalStore])
def test_append_and_list_run_events_in_order(store_factory) -> None:
    store = store_factory()
    first = make_event("event_001", round_number=1)
    second = make_event("event_002", round_number=2)

    store.append(first)
    store.append(second)

    assert store.list_run_events("run_001") == [first, second]


@pytest.mark.parametrize("store_factory", [InMemoryJournalStore, SQLiteJournalStore])
def test_rejects_duplicate_event_ids(store_factory) -> None:
    store = store_factory()
    event = make_event("event_001")

    store.append(event)

    with pytest.raises(DuplicateJournalEventError, match="event_001"):
        store.append(event)


@pytest.mark.parametrize("store_factory", [InMemoryJournalStore, SQLiteJournalStore])
def test_filters_events_by_agent(store_factory) -> None:
    store = store_factory()
    collector_event = make_event("event_001", agent="collector", round_number=1)
    analyst_event = make_event("event_002", agent="analyst", round_number=2)

    store.append(collector_event)
    store.append(analyst_event)

    assert store.list_agent_events("run_001", "analyst") == [analyst_event]


@pytest.mark.parametrize("store_factory", [InMemoryJournalStore, SQLiteJournalStore])
def test_preserves_event_json_fields(store_factory) -> None:
    store = store_factory()
    event = make_event("event_001")

    store.append(event)
    loaded = store.list_run_events("run_001")[0]

    assert loaded.tool_calls[0].args == {"url": "https://example.com"}
    assert loaded.output_artifact_ids == ["artifact_event_001"]
    assert loaded.signals == ["progress"]
    assert loaded.timestamp == "2026-06-03T14:22:01Z"


def test_sqlite_store_can_reopen_file_backed_journal(tmp_path) -> None:
    db_path = tmp_path / "journal.sqlite"
    first_store = SQLiteJournalStore(db_path)
    event = make_event("event_001")

    first_store.append(event)
    second_store = SQLiteJournalStore(db_path)

    assert second_store.list_run_events("run_001") == [event]
