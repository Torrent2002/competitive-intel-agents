from competitive_intel_agents.agents import CollectorAgent
from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.harness import RuntimeHarness
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AgentProfile,
    AgentState,
    CompetitiveIntelRequest,
    RunContext,
    ToolResult,
)
from competitive_intel_agents.runtime import FakeWebFetch, FakeWebSearch, ToolRuntime


def make_context(max_rounds: int = 4) -> RunContext:
    return RunContext(
        run_id="run_001",
        request=CompetitiveIntelRequest(
            company="ACME",
            market="collaboration software",
            competitors=["Globex"],
            questions=["pricing"],
        ),
        agent_profiles={
            "collector": AgentProfile(
                agent="collector",
                max_rounds=max_rounds,
                allowed_tools=["web_search", "web_fetch"],
            )
        },
    )


def make_harness() -> RuntimeHarness:
    tools = ToolRuntime()
    tools.register(FakeWebSearch())
    tools.register(FakeWebFetch())
    return RuntimeHarness(InMemoryJournalStore(), tools)


def test_collector_first_round_requests_search_query_from_run_input() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store)

    result = collector.run_round(make_context(), AgentState(agent="collector", round=1))

    assert result.completed is False
    assert len(result.tool_calls) >= 1
    assert result.tool_calls[0].name == "web_search"
    assert result.tool_calls[0].requested_by == "collector"
    queries = " ".join(c.args.get("query", "") for c in result.tool_calls)
    assert "ACME" in queries
    assert "pricing" in queries


def test_collector_turns_search_results_into_deduped_fetch_calls() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store)
    state = AgentState(
        agent="collector",
        round=2,
        memory={
            "tool_results": [
                ToolResult(
                    tool_call_id="search_1",
                    ok=True,
                    data={
                        "results": [
                            {
                                "title": "One",
                                "url": "https://example.com/a",
                                "snippet": "First result",
                            },
                            {
                                "title": "Duplicate",
                                "url": "https://example.com/a",
                                "snippet": "Duplicate result",
                            },
                            {
                                "title": "Two",
                                "url": "https://example.com/b",
                                "snippet": "Second result",
                            },
                        ]
                    },
                ).to_dict()
            ]
        },
    )

    result = collector.run_round(make_context(), state)

    assert result.completed is False
    assert [call.name for call in result.tool_calls] == ["web_fetch", "web_fetch"]
    assert [call.args["url"] for call in result.tool_calls] == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_collector_saves_fetch_results_as_source_artifacts() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store, target_sources=2)
    state = AgentState(
        agent="collector",
        round=3,
        memory={
            "tool_results": [
                ToolResult(
                    tool_call_id="fetch_1",
                    ok=True,
                    data={
                        "url": "https://example.com/a",
                        "title": "Page A",
                        "content": "A detailed page about ACME.",
                    },
                ).to_dict(),
                ToolResult(
                    tool_call_id="fetch_2",
                    ok=True,
                    data={
                        "url": "https://example.com/b",
                        "title": "Page B",
                        "content": "Another detailed page about ACME.",
                    },
                ).to_dict(),
            ]
        },
    )

    result = collector.run_round(make_context(), state)
    sources = store.list_sources("run_001")

    assert result.completed is True
    assert result.output_artifact_ids == ["source_run_001_001", "source_run_001_002"]
    assert [source.url for source in sources] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert sources[0].title == "Page A"
    assert sources[0].snippet == "A detailed page about ACME."


def test_collector_skips_urls_already_saved() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store)
    context = make_context()
    first_state = AgentState(
        agent="collector",
        round=3,
        memory={
            "tool_results": [
                ToolResult(
                    tool_call_id="fetch_1",
                    ok=True,
                    data={
                        "url": "https://example.com/a",
                        "title": "Page A",
                        "content": "A detailed page about ACME.",
                    },
                ).to_dict()
            ]
        },
    )
    duplicate_state = AgentState(
        agent="collector",
        round=4,
        memory={
            "tool_results": [
                ToolResult(
                    tool_call_id="fetch_2",
                    ok=True,
                    data={
                        "url": "https://example.com/a",
                        "title": "Page A duplicate",
                        "content": "Duplicate content.",
                    },
                ).to_dict()
            ]
        },
    )

    collector.run_round(context, first_state)
    duplicate = collector.run_round(context, duplicate_state)

    assert duplicate.output_artifact_ids == []
    assert len(store.list_sources("run_001")) == 1


def test_collector_can_run_through_harness_with_fake_tools() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store, target_sources=2)
    harness = make_harness()

    result = harness.run_agent(make_context(max_rounds=4), collector)

    assert result.decision == "stop"
    assert len(result.output_artifact_ids) >= 2
    assert all(aid.startswith("source_run_001_") for aid in result.output_artifact_ids)
    assert len(store.list_sources("run_001")) >= 2
