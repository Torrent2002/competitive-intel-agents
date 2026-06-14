from pathlib import Path

from competitive_intel_agents.runtime import (
    BingSearch,
    CachedWebFetch,
    LocalContentStore,
    PersistedContentTool,
    FallbackSearch,
    DuckDuckGoSearch,
    HttpClient,
    SerperSearch,
    WebFetchTool,
    WebSearchTool,
    make_default_search_adapter,
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


def test_cached_web_fetch_persists_legacy_cached_content(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    url = "https://example.com/legacy"
    import hashlib
    import json

    cache_path = cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.json"
    cache_path.write_text(
        json.dumps(
            {
                "url": url,
                "title": "Legacy",
                "content": "Legacy full content " * 50,
            }
        ),
        encoding="utf-8",
    )

    class UnusedFetcher:
        name = "web_fetch"

        def run(self, args: dict) -> dict:
            raise AssertionError("cache should be used")

    fetch = CachedWebFetch(
        fetcher=PersistedContentTool(
            UnusedFetcher(),
            LocalContentStore(tmp_path / "content"),
        ),
        cache_dir=cache_dir,
    )

    result = fetch.run({"url": url})

    assert result["cached"] is True
    assert result["content_ref"].startswith("file:")
    assert Path(result["content_ref"].removeprefix("file:")).exists()
    assert json.loads(cache_path.read_text(encoding="utf-8"))["content_ref"] == result["content_ref"]


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


# ── Serper search adapter (Module 34) ──────────────────────────


class StubSerperTransport:
    """Records requests and returns canned responses."""

    def __init__(self, response: dict | Exception) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post_json(self, url: str, headers: dict, payload: dict, timeout: float) -> dict:
        self.calls.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_serper_search_parses_organic_results() -> None:
    transport = StubSerperTransport(
        {
            "organic": [
                {
                    "title": "Notion pricing — official",
                    "link": "https://www.notion.so/pricing",
                    "snippet": "Plans for individuals and teams.",
                },
                {
                    "title": "Notion vs Coda comparison",
                    "link": "https://example.com/compare",
                    "snippet": "Feature-by-feature comparison.",
                },
            ]
        }
    )
    adapter = SerperSearch(api_key="test-key", transport=transport)

    results = adapter.search("Notion pricing", limit=5)

    assert results == [
        {
            "url": "https://www.notion.so/pricing",
            "title": "Notion pricing — official",
            "snippet": "Plans for individuals and teams.",
        },
        {
            "url": "https://example.com/compare",
            "title": "Notion vs Coda comparison",
            "snippet": "Feature-by-feature comparison.",
        },
    ]
    assert transport.calls[0]["headers"]["X-API-KEY"] == "test-key"
    assert transport.calls[0]["payload"]["q"] == "Notion pricing"


def test_serper_search_returns_empty_on_transport_error() -> None:
    transport = StubSerperTransport(OSError("connection reset"))
    adapter = SerperSearch(api_key="test-key", transport=transport)

    results = adapter.search("anything", limit=5)

    assert results == []


def test_serper_search_is_inert_without_api_key() -> None:
    """Without an API key the adapter should be silently empty so it
    can sit at the head of a fallback chain in unauthenticated runs."""
    transport = StubSerperTransport({"organic": [{"title": "ignored", "link": "https://x"}]})
    adapter = SerperSearch(api_key="", transport=transport)

    results = adapter.search("anything", limit=5)

    assert results == []
    # No request should have been issued either — keyless mode skips
    # the network call entirely instead of getting a 401 back.
    assert transport.calls == []


def test_make_default_search_adapter_prefers_serper_when_keyed(monkeypatch) -> None:
    monkeypatch.delenv("CIA_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("CIA_SERPER_API_KEY", "live-key")
    # BingSearch() default-constructs BrowserHttpClient which imports
    # curl_cffi — not always present in local CI. Stub it out.
    _stub_browser_client(monkeypatch)

    adapter = make_default_search_adapter()

    assert isinstance(adapter, FallbackSearch)
    assert isinstance(adapter._adapters[0], SerperSearch)
    # HTML fallbacks remain in the chain.
    assert any(isinstance(a, DuckDuckGoSearch) for a in adapter._adapters)


def test_make_default_search_adapter_keyless_keeps_html_only(monkeypatch) -> None:
    monkeypatch.delenv("CIA_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("CIA_SERPER_API_KEY", raising=False)
    _stub_browser_client(monkeypatch)

    adapter = make_default_search_adapter()

    assert isinstance(adapter, FallbackSearch)
    # No SerperSearch in the chain when there is no key — preserves
    # the prior keyless behavior exactly.
    assert not any(isinstance(a, SerperSearch) for a in adapter._adapters)
    assert any(isinstance(a, DuckDuckGoSearch) for a in adapter._adapters)


def test_make_default_search_adapter_serper_only_does_not_import_curl_cffi(
    monkeypatch,
) -> None:
    """``provider="serper"`` must build the chain WITHOUT touching
    BingSearch — otherwise hosts that only need the API path can't run
    the factory unless they also install ``curl_cffi``. Regression test
    for the eager-construction bug that crashed run_3dc810266d52."""

    # Make BrowserHttpClient explosive: any attempt to instantiate it
    # raises, simulating a host without curl_cffi installed. We do NOT
    # call _stub_browser_client here — the point is to prove the
    # serper-only path never reaches BrowserHttpClient.
    class _Explodes:
        def __init__(self, *a, **kw):
            raise ImportError("simulated: curl_cffi not installed")

    import competitive_intel_agents.runtime.web_tools as wt

    monkeypatch.setattr(wt, "BrowserHttpClient", _Explodes)
    monkeypatch.delenv("CIA_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("CIA_SERPER_API_KEY", "live-key")

    adapter = make_default_search_adapter(provider="serper")

    assert isinstance(adapter, FallbackSearch)
    assert len(adapter._adapters) == 1
    assert isinstance(adapter._adapters[0], SerperSearch)


def _stub_browser_client(monkeypatch) -> None:
    """Replace BrowserHttpClient with a no-op so its curl_cffi import
    doesn't fire when BingSearch() is default-constructed in tests."""

    class _Inert:
        def get_text(self, url: str, timeout: float = 10.0, headers: dict | None = None) -> str:
            return ""

    import competitive_intel_agents.runtime.web_tools as wt

    monkeypatch.setattr(wt, "BrowserHttpClient", _Inert)
