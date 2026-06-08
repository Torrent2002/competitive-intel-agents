from pathlib import Path

from competitive_intel_agents.runtime import (
    CachedWebFetch,
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
    client = StubHttpClient({"https://duckduckgo.com/html/?q=Notion+pricing": html})
    search = DuckDuckGoSearch(http_client=client)

    results = search.search("Notion pricing", limit=2)

    assert results[0]["title"] == "Result A"
    assert results[0]["url"] == "https://example.com/a"
    assert results[0]["snippet"] == "Snippet A"
    assert results[1]["url"] == "https://example.com/b"


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
