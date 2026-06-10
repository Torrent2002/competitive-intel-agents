from pathlib import Path

from competitive_intel_agents.runtime import (
    BingSearch,
    CachedWebFetch,
    LocalContentStore,
    PersistedContentTool,
    FallbackSearch,
    DuckDuckGoSearch,
    HttpClient,
    WebFetchTool,
    WebSearchTool,
)


class StubHttpClient:
    def __init__(self, payloads: dict[str, str]) -> None:
        self.payloads = payloads
        self.urls: list[str] = []

    def get_text(self, url: str, timeout: float = 10.0) -> str:
        self.urls.append(url)
        return self.payloads[url]


def test_web_search_tool_uses_adapter_and_limit() -> None:
    class Adapter:
        def search(self, query: str, limit: int = 5) -> list[dict]:
            return [
                {"title": f"{query} A", "url": "https://example.com/a"},
                {"title": f"{query} B", "url": "https://example.com/b"},
            ][:limit]

    tool = WebSearchTool(Adapter(), default_limit=1)

    result = tool.run({"query": "Notion pricing"})

    assert result["query"] == "Notion pricing"
    assert result["total_results"] == 1
    assert result["results"] == [{"title": "Notion pricing A", "url": "https://example.com/a"}]


def test_duckduckgo_search_parses_html_results_without_network() -> None:
    html = """
    <html>
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">Result A</a>
      <a class="result__snippet">Snippet A</a>
      <a class="result__a" href="https://example.com/b">Result B</a>
    </html>
    """
    client = StubHttpClient({"https://html.duckduckgo.com/html/?q=Notion+pricing": html})
    search = DuckDuckGoSearch(http_client=client)

    results = search.search("Notion pricing", limit=2)

    assert results[0]["title"] == "Result A"
    assert results[0]["url"] == "https://example.com/a"
    assert results[0]["snippet"] == "Snippet A"
    assert results[1]["url"] == "https://example.com/b"


def test_bing_search_parses_redirect_results_without_network() -> None:
    html = """
    <ol id="b_results">
      <li class="b_algo">
        <h2><a href="https://www.bing.com/ck/a?!&amp;u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9h&amp;ntb=1">Result A</a></h2>
        <div class="b_caption"><p>Snippet A</p></div>
      </li>
    </ol>
    """
    client = StubHttpClient(
        {"https://www.bing.com/search?q=Notion+pricing&mkt=en-US&setlang=en&cc=US": html}
    )
    search = BingSearch(http_client=client)

    results = search.search("Notion pricing", limit=1)

    assert results == [
        {"title": "Result A", "url": "https://example.com/a", "snippet": "Snippet A"}
    ]


def test_fallback_search_uses_next_adapter_when_first_returns_no_results() -> None:
    class EmptyAdapter:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def search(self, query: str, limit: int = 5) -> list[dict]:
            self.calls.append(query)
            return []

    class WorkingAdapter:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def search(self, query: str, limit: int = 5) -> list[dict]:
            self.calls.append((query, limit))
            return [{"title": "Result", "url": "https://example.com/result"}]

    empty = EmptyAdapter()
    working = WorkingAdapter()
    search = FallbackSearch([empty, working])

    results = search.search("Notion pricing", limit=3)

    assert results == [{"title": "Result", "url": "https://example.com/result"}]
    assert empty.calls == ["Notion pricing"]
    assert working.calls == [("Notion pricing", 3)]


def test_fallback_search_uses_next_adapter_when_first_raises() -> None:
    class BrokenAdapter:
        def search(self, query: str, limit: int = 5) -> list[dict]:
            raise RuntimeError("network down")

    class WorkingAdapter:
        def search(self, query: str, limit: int = 5) -> list[dict]:
            return [{"title": query, "url": "https://example.com"}]

    search = FallbackSearch([BrokenAdapter(), WorkingAdapter()])

    assert search.search("ByteDance", limit=1) == [
        {"title": "ByteDance", "url": "https://example.com"}
    ]


def test_web_fetch_tool_extracts_title_and_text_preview() -> None:
    html = """
    <html><head><title>Example Page</title><script>ignore()</script></head>
    <body><h1>Hello</h1><p>This is useful content.</p></body></html>
    """
    client = StubHttpClient({"https://example.com/a": html})
    tool = WebFetchTool(http_client=client, max_chars=40)

    result = tool.run({"url": "https://example.com/a"})

    assert result["url"] == "https://example.com/a"
    assert result["title"] == "Example Page"
    assert "Hello" in result["content"]
    assert "ignore" not in result["content"]
    assert len(result["content"]) <= 40


def test_persisted_content_tool_stores_full_text_and_returns_reference(tmp_path: Path) -> None:
    class LargeTextTool:
        name = "web_fetch"

        def run(self, args: dict) -> dict:
            return {
                "url": args["url"],
                "title": "Long page",
                "content": "Alpha Beta Gamma " * 200,
            }

    tool = PersistedContentTool(
        LargeTextTool(),
        content_store=LocalContentStore(tmp_path / "content"),
        summary_chars=80,
        preview_chars=30,
    )

    result = tool.run({"url": "https://example.com/long"})

    assert result["url"] == "https://example.com/long"
    assert result["title"] == "Long page"
    assert result["content_ref"].startswith("file:")
    assert result["content_hash"]
    assert result["char_count"] == len("Alpha Beta Gamma " * 200)
    assert result["summary"] == ("Alpha Beta Gamma " * 200)[:80]
    assert result["preview"] == ("Alpha Beta Gamma " * 200)[:30]
    assert result["content"] == result["summary"]

    path = Path(result["content_ref"].removeprefix("file:"))
    assert path.read_text(encoding="utf-8") == "Alpha Beta Gamma " * 200


def test_cached_web_fetch_reuses_workspace_cache(tmp_path: Path) -> None:
    client = StubHttpClient({"https://example.com/a": "<title>A</title><p>Fresh</p>"})
    fetch = CachedWebFetch(
        fetcher=WebFetchTool(http_client=client),
        cache_dir=tmp_path / "cache",
    )

    first = fetch.run({"url": "https://example.com/a"})
    second = fetch.run({"url": "https://example.com/a"})

    assert first["content"] == second["content"]
    assert first["cached"] is False
    assert second["cached"] is True
    assert client.urls == ["https://example.com/a"]


def test_http_client_reports_fetch_errors() -> None:
    class BrokenOpener:
        def __call__(self, request, timeout):
            raise OSError("boom")

    client = HttpClient(opener=BrokenOpener())

    try:
        client.get_text("https://example.com")
    except RuntimeError as exc:
        assert "failed to fetch" in str(exc)
    else:
        raise AssertionError("expected fetch failure")
