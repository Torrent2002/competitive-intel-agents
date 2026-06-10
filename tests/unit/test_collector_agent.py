from competitive_intel_agents.agents import CollectorAgent
from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.harness import RuntimeHarness
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AgentProfile,
    AgentState,
    CompetitiveIntelRequest,
    RunContext,
    SourceArtifact,
    ToolResult,
)
from competitive_intel_agents.runtime import FakeWebFetch, FakeWebSearch, ToolRuntime


class EmptySearch:
    name = "web_search"

    def run(self, args: dict) -> dict:
        return {
            "query": args["query"],
            "results": [],
            "total_results": 0,
        }


class SelectiveFetch:
    name = "web_fetch"

    def run(self, args: dict) -> dict:
        url = args["url"]
        if url in {
            "https://www.matrixone.com",
            "https://www.oceanbase.com",
        }:
            return {
                "url": url,
                "title": f"Official {url}",
                "content": f"Official content from {url}",
            }
        raise RuntimeError(f"not reachable: {url}")


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


def test_collector_preserves_content_reference_metadata_when_saving_source() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store, target_sources=1)
    tool_result = ToolResult(
        tool_call_id="fetch_001",
        ok=True,
        data={
            "url": "https://example.com/acme",
            "title": "ACME market page",
            "content": "ACME pricing and audience evidence.",
            "content_ref": "file:/tmp/acme.txt",
            "content_hash": "abc123",
            "char_count": 1234,
            "summary": "ACME pricing and audience evidence.",
            "preview": "ACME pricing",
        },
    )

    result = collector.run_round(
        make_context(),
        AgentState(
            agent="collector",
            round=2,
            memory={"tool_results": [tool_result.to_dict()]},
        ),
    )

    assert result.output_artifact_ids
    source = store.get_artifact(result.output_artifact_ids[0])
    assert source.metadata["content_ref"] == "file:/tmp/acme.txt"
    assert source.metadata["content_hash"] == "abc123"
    assert source.metadata["char_count"] == 1234
    assert source.metadata["summary"] == "ACME pricing and audience evidence."


def test_collector_marks_every_initial_coverage_slot_as_attempted() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store)

    result = collector.run_round(make_context(), AgentState(agent="collector", round=1))

    attempted = {
        signal.removeprefix("attempted:")
        for signal in result.signals
        if signal.startswith("attempted:")
    }

    assert attempted >= {
        "ACME:official",
        "ACME:features",
        "ACME:pricing",
        "ACME:positioning",
        "ACME:use cases",
        "ACME:limitations",
        "Globex:official",
        "Globex:features",
        "Globex:pricing",
        "Globex:positioning",
        "Globex:use cases",
        "Globex:limitations",
        "ACME:comparison:Globex",
    }


def test_collector_does_not_stop_on_source_count_before_competitor_attempts() -> None:
    store = InMemoryArtifactStore()
    store.save_source(
        SourceArtifact(
            id="source_run_001_001",
            run_id="run_001",
            url="https://acme.example/product",
            title="ACME product",
            snippet="ACME product evidence.",
            metadata={"entity": "ACME", "dimension": "official"},
        )
    )
    store.save_source(
        SourceArtifact(
            id="source_run_001_002",
            run_id="run_001",
            url="https://acme.example/pricing",
            title="ACME pricing",
            snippet="ACME pricing evidence.",
            metadata={"entity": "ACME", "dimension": "pricing"},
        )
    )
    collector = CollectorAgent(store, target_sources=2)

    result = collector.run_round(make_context(), AgentState(agent="collector", round=1))

    assert result.completed is False
    assert result.tool_calls
    assert any(
        call.args["metadata"]["entity"] == "Globex"
        for call in result.tool_calls
    )
    assert any(signal.startswith("attempted:Globex:") for signal in result.signals)


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


def test_collector_falls_back_to_direct_official_urls_when_search_has_no_results() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store)
    context = RunContext(
        run_id="run_search_down",
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
    first = collector.run_round(context, AgentState(agent="collector", round=1))

    fallback = collector.run_round(
        context,
        AgentState(
            agent="collector",
            round=2,
            memory={
                "tool_results": [
                    ToolResult(
                        tool_call_id=call.id,
                        ok=True,
                        data={"query": call.args["query"], "results": []},
                    ).to_dict()
                    for call in first.tool_calls
                ]
            },
        ),
    )

    urls = [call.args["url"] for call in fallback.tool_calls]

    assert fallback.completed is False
    assert "direct_url_fallback" in fallback.signals
    assert "https://www.matrixone.com" in urls
    assert "https://www.oceanbase.com" in urls


def test_collector_harness_survives_search_down_with_direct_url_fallbacks() -> None:
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    tools = ToolRuntime()
    tools.register(EmptySearch())
    tools.register(SelectiveFetch())
    harness = RuntimeHarness(journal, tools)
    collector = CollectorAgent(store, target_sources=2)
    context = RunContext(
        run_id="run_search_down",
        request=CompetitiveIntelRequest(
            company="MatrixOne",
            competitors=["OceanBase"],
            questions=["主要功能", "价格"],
        ),
        agent_profiles={
            "collector": AgentProfile(
                agent="collector",
                max_rounds=8,
                allowed_tools=["web_search", "web_fetch"],
            )
        },
    )

    result = harness.run_agent(context, collector)
    sources = store.list_sources("run_search_down")

    assert result.decision == "stop"
    assert {source.metadata.get("entity") for source in sources} >= {
        "MatrixOne",
        "OceanBase",
    }
    assert any(
        "direct_url_fallback" in event.signals
        for event in journal.list_run_events("run_search_down")
    )


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

    assert result.completed is False
    assert result.output_artifact_ids == ["source_run_001_001", "source_run_001_002"]
    assert "coverage_incomplete" in result.signals
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


def test_collector_marks_partial_coverage_when_competitor_is_missing() -> None:
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

    assert first_save.completed is True
    assert "coverage_partial" in first_save.signals

    assert acme_fetch.tool_calls[0].args["url"] == "https://acme.com/product"


def test_collector_allows_partial_coverage_once_enough_sources_exist() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store, target_sources=2)
    context = make_context(max_rounds=10)

    collector.run_round(context, AgentState(agent="collector", round=1))
    result = collector.run_round(
        context,
        AgentState(
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
                            "content": "Useful ACME evidence.",
                        },
                    ).to_dict(),
                    ToolResult(
                        tool_call_id="fetch_2",
                        ok=True,
                        data={
                            "url": "https://example.com/b",
                            "title": "Page B",
                            "content": "Useful market evidence.",
                        },
                    ).to_dict(),
                ]
            },
        ),
    )

    assert result.completed is True
    assert "coverage_partial" in result.signals
    assert result.output_artifact_ids == ["source_run_001_001", "source_run_001_002"]


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
    journal = InMemoryJournalStore()
    tools = ToolRuntime()
    tools.register(FakeWebSearch())
    tools.register(FakeWebFetch())
    harness = RuntimeHarness(journal, tools)

    result = harness.run_agent(make_context(max_rounds=8), collector)

    assert result.decision == "stop"
    assert len(result.output_artifact_ids) >= 2
    assert all(aid.startswith("source_run_001_") for aid in result.output_artifact_ids)
    assert len(store.list_sources("run_001")) >= 2
    assert any(
        "coverage_partial" in event.signals
        for event in journal.list_run_events("run_001")
    )


def test_collector_expands_industry_queries_for_audience_and_market_share() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store)
    context = RunContext(
        run_id="run_reading",
        request=CompetitiveIntelRequest(
            company="番茄小说",
            competitors=["起点阅读"],
            questions=["受众群体，市场份额"],
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
    metadata = [call.args["metadata"] for call in result.tool_calls]

    assert any("QuestMobile" in query for query in queries)
    assert any("易观" in query for query in queries)
    assert any("月活" in query or "MAU" in query for query in queries)
    assert any("免费阅读" in query and "付费阅读" in query for query in queries)
    assert any(item["source_type"] == "data_provider" for item in metadata)
    assert any(item["dimension"] == "market_share" for item in metadata)
    assert any(item["dimension"] == "audience" for item in metadata)


def test_collector_prioritizes_high_quality_urls_before_low_quality_download_sites() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store)
    search_results = [
        {
            "title": "App download",
            "url": "https://sj.qq.com/appdetail/com.example",
            "snippet": "download app",
            "metadata": {"dimension": "market_share", "source_type": "web"},
        },
        {
            "title": "QuestMobile reading market report",
            "url": "https://www.questmobile.com.cn/research/report",
            "snippet": "market share and MAU report",
            "metadata": {"dimension": "market_share", "source_type": "data_provider"},
        },
        {
            "title": "Official product page",
            "url": "https://fanqienovel.com/library",
            "snippet": "official product",
            "metadata": {"dimension": "official", "source_type": "official"},
        },
    ]

    selected = collector._select_urls(search_results, count=3)

    assert selected[0]["url"] == "https://www.questmobile.com.cn/research/report"
    assert selected[-1]["url"] == "https://sj.qq.com/appdetail/com.example"


def test_collector_saves_extract_quality_and_covered_dimensions_metadata() -> None:
    store = InMemoryArtifactStore()
    collector = CollectorAgent(store, target_sources=1)
    content = (
        "番茄小说月活用户增长，用户画像覆盖18-35岁年轻读者，"
        "免费阅读市场份额提升，起点阅读保持付费阅读优势。"
    )

    result = collector.run_round(
        make_context(),
        AgentState(
            agent="collector",
            round=2,
            memory={
                "tool_results": [
                    ToolResult(
                        tool_call_id="fetch_001",
                        ok=True,
                        data={
                            "url": "https://example.com/report",
                            "title": "Reading market report",
                            "content": content,
                            "char_count": len(content),
                        },
                    ).to_dict()
                ]
            },
        ),
    )

    source = store.get_artifact(result.output_artifact_ids[0])

    assert source.metadata["extract_quality"] == "good"
    assert "audience" in source.metadata["covered_dimensions"]
    assert "market_share" in source.metadata["covered_dimensions"]
