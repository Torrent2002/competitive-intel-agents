"""Real web search/fetch adapters built on standard-library HTTP."""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from typing import Callable, Protocol
from urllib import parse, request as urllib_request


class SearchAdapter(Protocol):
    def search(self, query: str, limit: int = 5) -> list[dict]:
        ...


class HttpClient:
    """Small HTTP client wrapper so tests can inject transports."""

    def __init__(self, opener: Callable | None = None) -> None:
        self._opener = opener or urllib_request.urlopen

    def get_text(self, url: str, timeout: float = 10.0) -> str:
        req = urllib_request.Request(
            url,
            headers={
                "User-Agent": "competitive-intel-agents/0.1 (+local research tool)"
            },
        )
        try:
            with self._opener(req, timeout=timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except Exception as exc:
            raise RuntimeError(f"failed to fetch {url}: {exc}") from exc


class DuckDuckGoSearch:
    """HTML-search adapter for optional real local collection."""

    def __init__(
        self,
        http_client: HttpClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._http_client = http_client or HttpClient()
        self._timeout = timeout

    def search(self, query: str, limit: int = 5) -> list[dict]:
        encoded = parse.quote_plus(query)
        html_text = self._http_client.get_text(
            f"https://duckduckgo.com/html/?q={encoded}",
            timeout=self._timeout,
        )
        return _parse_duckduckgo_html(html_text, limit)


class WebSearchTool:
    """ToolRuntime-compatible search tool using a pluggable adapter."""

    name = "web_search"

    def __init__(self, adapter: SearchAdapter, default_limit: int = 5) -> None:
        self._adapter = adapter
        self._default_limit = default_limit

    def run(self, args: dict) -> dict:
        query = str(args.get("query", "")).strip()
        if not query:
            raise ValueError("query is required")
        limit = int(args.get("limit", self._default_limit))
        results = self._adapter.search(query, limit=limit)
        return {
            "query": query,
            "results": results[:limit],
            "total_results": len(results[:limit]),
        }


class WebFetchTool:
    """Fetch a web page and return title plus cleaned text preview."""

    name = "web_fetch"

    def __init__(
        self,
        http_client: HttpClient | None = None,
        timeout: float = 10.0,
        max_chars: int = 2000,
    ) -> None:
        self._http_client = http_client or HttpClient()
        self._timeout = timeout
        self._max_chars = max_chars

    def run(self, args: dict) -> dict:
        url = str(args.get("url", "")).strip()
        if not url:
            raise ValueError("url is required")
        html_text = self._http_client.get_text(url, timeout=self._timeout)
        return {
            "url": url,
            "title": _extract_title(html_text) or url,
            "content": _clean_html_text(html_text)[: self._max_chars],
        }


class CachedWebFetch:
    """Cache web_fetch outputs in a workspace directory."""

    name = "web_fetch"

    def __init__(self, fetcher: WebFetchTool, cache_dir: str | Path) -> None:
        self._fetcher = fetcher
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def run(self, args: dict) -> dict:
        url = str(args.get("url", "")).strip()
        cache_path = self._cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.json"
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            payload["cached"] = True
            return payload
        payload = self._fetcher.run(args)
        payload["cached"] = False
        cache_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return payload


def _parse_duckduckgo_html(html_text: str, limit: int) -> list[dict]:
    results: list[dict] = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.DOTALL,
    )
    snippets = [
        _strip_tags(match)
        for match in re.findall(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            html_text,
            flags=re.DOTALL,
        )
    ]
    for index, match in enumerate(pattern.finditer(html_text)):
        href = html.unescape(match.group("href"))
        url = _normalize_duckduckgo_url(href)
        if not url:
            continue
        results.append(
            {
                "title": _strip_tags(match.group("title")),
                "url": url,
                "snippet": snippets[index] if index < len(snippets) else "",
            }
        )
        if len(results) >= limit:
            break
    return results


def _normalize_duckduckgo_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = parse.urlparse(href)
    query = parse.parse_qs(parsed.query)
    if "uddg" in query:
        return query["uddg"][0]
    return href


def _extract_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    return _strip_tags(match.group(1)) if match else ""


def _clean_html_text(html_text: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html_text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = _strip_tags(text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()
