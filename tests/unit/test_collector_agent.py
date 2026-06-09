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


def test_collector_first_round_builds_entity_dimension_coverage_queries() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store)

    result = collector.run_round(make_context(), AgentState(agent="collector", round=1))

    calls = result.tool_calls
    queries = [call.args["query"] for call in calls]
    metadata = [call.args["metadata"] for call in calls]

    assert any(item["entity"] == "ACME" and item["entity_role"] == "self" for item in metadata)
    assert any(
        item["entity"] == "Globex" and item["entity_role"] == "competitor"
        for item in metadata
    )
    assert any(item["dimension"] == "official" for item in metadata)
    assert any(item["dimension"] == "pricing" for item in metadata)
    assert any(item["dimension"] == "comparison" for item in metadata)
    assert any("ACME official" in query for query in queries)
    assert any("Globex official" in query for query in queries)
    assert any("ACME vs Globex" in query for query in queries)


def test_collector_uses_chinese_query_terms_for_chinese_requests() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store)
    context = RunContext(
        run_id="run_zh",
        request=CompetitiveIntelRequest(
            company="MatrixOne",
            competitors=["OceanBase"],
            questions=["主要功能", "价格"],
        ),
        agent_profiles={
            "collector": AgentProfile(
                agent="collector",
                max_rounds=10,
                allowed_tools=["web_search", "web_fetch"],
            )
        },
    )

    result = collector.run_round(context, AgentState(agent="collector", round=1))
    queries = [call.args["query"] for call in result.tool_calls]

    assert "MatrixOne 官网 产品" in queries
    assert "MatrixOne 文档 功能" in queries
    assert "MatrixOne 价格" in queries
    assert "MatrixOne 对比 OceanBase" in queries


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


def test_collector_attaches_coverage_metadata_to_saved_sources() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store, target_sources=1)
    context = make_context()
    first = collector.run_round(context, AgentState(agent="collector", round=1))
    official_call = next(
        call
        for call in first.tool_calls
        if call.args["metadata"]["entity"] == "ACME"
        and call.args["metadata"]["dimension"] == "official"
    )

    fetch = collector.run_round(
        context,
        AgentState(
            agent="collector",
            round=2,
            memory={
                "tool_results": [
                    ToolResult(
                        tool_call_id="search_1",
                        ok=True,
                        data={
                            "query": official_call.args["query"],
                            "results": [
                                {
                                    "title": "ACME Official",
                                    "url": "https://acme.com/product",
                                    "snippet": "Official ACME product page.",
                                }
                            ],
                        },
                    ).to_dict()
                ]
            },
        ),
    )
    collector.run_round(
        context,
        AgentState(
            agent="collector",
            round=3,
            memory={
                "tool_results": [
                    ToolResult(
                        tool_call_id=fetch.tool_calls[0].id,
                        ok=True,
                        data={
                            "url": "https://acme.com/product",
                            "title": "ACME Official",
                            "content": "Official ACME product information.",
                        },
                    ).to_dict()
                ]
            },
        ),
    )

    source = store.list_sources("run_001")[0]

    assert source.metadata["entity"] == "ACME"
    assert source.metadata["entity_role"] == "self"
    assert source.metadata["dimension"] == "official"
    assert source.metadata["source_type"] == "official"
    assert source.metadata["is_official"] is True


def test_collector_requires_self_and_competitor_coverage_before_completion() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store, target_sources=1)
    context = make_context(max_rounds=10)
    first = collector.run_round(context, AgentState(agent="collector", round=1))
    acme_query = next(
        call.args["query"]
        for call in first.tool_calls
        if call.args["metadata"]["entity"] == "ACME"
        and call.args["metadata"]["dimension"] == "official"
    )
    globex_query = next(
        call.args["query"]
        for call in first.tool_calls
        if call.args["metadata"]["entity"] == "Globex"
        and call.args["metadata"]["dimension"] == "official"
    )
    acme_fetch = collector.run_round(
        context,
        AgentState(
            agent="collector",
            round=2,
            memory={
                "tool_results": [
                    ToolResult(
                        tool_call_id="search_acme",
                        ok=True,
                        data={
                            "query": acme_query,
                            "results": [
                                {
                                    "url": "https://acme.com/product",
                                    "title": "ACME",
                                    "snippet": "Official ACME product details.",
                                }
                            ],
                        },
                    ).to_dict()
                ]
            },
        ),
    )

    first_save = collector.run_round(
        context,
        AgentState(
            agent="collector",
            round=3,
            memory={
                "tool_results": [
                    ToolResult(
                        tool_call_id="fetch_self",
                        ok=True,
                        data={
                            "url": "https://acme.com/product",
                            "title": "ACME",
                            "content": "Official ACME product details.",
                        },
                    ).to_dict()
                ]
            },
        ),
    )

    assert first_save.completed is False
    assert "coverage_incomplete" in first_save.signals

    assert acme_fetch.tool_calls[0].args["url"] == "https://acme.com/product"
    globex_fetch = collector.run_round(
        context,
        AgentState(
            agent="collector",
            round=4,
            memory={
                "tool_results": [
                    ToolResult(
                        tool_call_id="search_globex",
                        ok=True,
                        data={
                            "query": globex_query,
                            "results": [
                                {
                                    "url": "https://globex.com/product",
                                    "title": "Globex",
                                    "snippet": "Official Globex product details.",
                                }
                            ],
                        },
                    ).to_dict()
                ]
            },
        ),
    )
    second_save = collector.run_round(
        context,
        AgentState(
            agent="collector",
            round=4,
            memory={
                "tool_results": [
                    ToolResult(
                        tool_call_id="fetch_competitor",
                        ok=True,
                        data={
                            "url": "https://globex.com/product",
                            "title": "Globex",
                            "content": "Official Globex product details.",
                        },
                    ).to_dict()
                ]
            },
        ),
    )

    assert globex_fetch.tool_calls[0].args["url"] == "https://globex.com/product"
    assert second_save.completed is True


def test_collector_continues_fetching_pending_urls_until_target_is_met() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store, target_sources=5)
    context = make_context(max_rounds=10)
    search_results = [
        {
            "title": f"Page {index}",
            "url": f"https://example{index}.com/page",
            "snippet": f"Result {index}",
        }
        for index in range(8)
    ]

    first_fetch = collector.run_round(
        context,
        AgentState(
            agent="collector",
            round=2,
            memory={
                "tool_results": [
                    ToolResult(
                        tool_call_id="search_1",
                        ok=True,
                        data={"results": search_results},
                    ).to_dict()
                ]
            },
        ),
    )
    partial_save = collector.run_round(
        context,
        AgentState(
            agent="collector",
            round=3,
            memory={
                "tool_results": [
                    ToolResult(
                        tool_call_id=f"fetch_{index}",
                        ok=True,
                        data={
                            "url": f"https://example{index}.com/page",
                            "title": f"Page {index}",
                            "content": "Useful ACME evidence.",
                        },
                    ).to_dict()
                    for index in range(3)
                ]
            },
        ),
    )

    assert len(first_fetch.tool_calls) == 5
    assert partial_save.completed is False
    assert partial_save.output_artifact_ids == [
        "source_run_001_001",
        "source_run_001_002",
        "source_run_001_003",
    ]
    assert [call.args["url"] for call in partial_save.tool_calls] == [
        "https://example5.com/page",
        "https://example6.com/page",
        "https://example7.com/page",
    ]


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

    result = harness.run_agent(make_context(max_rounds=8), collector)

    assert result.decision == "stop"
    assert len(result.output_artifact_ids) >= 2
    assert all(aid.startswith("source_run_001_") for aid in result.output_artifact_ids)
    assert len(store.list_sources("run_001")) >= 2
    assert {
        source.metadata.get("entity")
        for source in store.list_sources("run_001")
        if source.metadata.get("entity")
    } >= {"ACME", "Globex"}
