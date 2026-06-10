"""Real web search/fetch adapters built on standard-library HTTP."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import base64
from pathlib import Path
from typing import Callable, Protocol
from urllib import parse, request as urllib_request


def _ensure_ssl_certs() -> None:
    """Auto-detect SSL cert file for Homebrew Python on macOS."""
    if os.environ.get("SSL_CERT_FILE"):
        return
    for cert_path in (
        "/etc/ssl/cert.pem",
        "/opt/homebrew/etc/openssl@3/cert.pem",
        "/usr/local/etc/openssl@3/cert.pem",
    ):
        if Path(cert_path).exists():
            os.environ["SSL_CERT_FILE"] = cert_path
            return


class SearchAdapter(Protocol):
    def search(self, query: str, limit: int = 5) -> list[dict]:
        ...


class HttpClient:
    """Small HTTP client wrapper so tests can inject transports."""

    def __init__(self, opener: Callable | None = None) -> None:
        self._opener = opener or urllib_request.urlopen

    def get_text(self, url: str, timeout: float = 10.0) -> str:
        _ensure_ssl_certs()
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
        results: list[dict] = []
        last_error = ""
        # Try primary HTML endpoint first
        try:
            html_text = self._http_client.get_text(
                f"https://html.duckduckgo.com/html/?q={encoded}",
                timeout=self._timeout,
            )
            results = _parse_duckduckgo_html(html_text, limit)
            if not results:
                last_error = f"html:0_results(len={len(html_text)})"
        except Exception as exc:
            last_error = f"html:{exc}"
        # Fallback to lite version
        if not results:
            try:
                html_text = self._http_client.get_text(
                    f"https://lite.duckduckgo.com/lite/?q={encoded}",
                    timeout=self._timeout,
                )
                results = _parse_duckduckgo_lite(html_text, limit)
                if not results:
                    last_error += f" lite:0_results(len={len(html_text)})"
            except Exception as exc:
                last_error += f" lite:{exc}"
        if not results:
            import sys
            print(
                f"[ddg] query={query[:50]!r} results=0 error={last_error}",
                file=sys.stderr,
            )
            # Dump first bit of HTML to diagnose parsing failures
            try:
                print(f"[ddg] html preview: {html_text[:300]!r}", file=sys.stderr)
            except Exception:
                pass
        return results


class BingSearch:
    """Bing HTML-search adapter used when DuckDuckGo is unavailable."""

    def __init__(
        self,
        http_client: HttpClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._http_client = http_client or HttpClient()
        self._timeout = timeout

    def search(self, query: str, limit: int = 5) -> list[dict]:
        encoded = parse.quote_plus(query)
        market = "zh-CN" if _contains_cjk(query) else "en-US"
        language = "zh-Hans" if market == "zh-CN" else "en"
        try:
            html_text = self._http_client.get_text(
                f"https://www.bing.com/search?q={encoded}&mkt={market}"
                f"&setlang={language}&cc={'CN' if market == 'zh-CN' else 'US'}",
                timeout=self._timeout,
            )
        except Exception as exc:
            import sys

            print(
                f"[bing] query={query[:50]!r} results=0 error={exc}",
                file=sys.stderr,
            )
            return []
        results = _parse_bing_html(html_text, limit)
        if not results:
            import sys

            print(
                f"[bing] query={query[:50]!r} results=0 parsed_empty(len={len(html_text)})",
                file=sys.stderr,
            )
        return results


class FallbackSearch:
    """Try search adapters in order until one returns results."""

    def __init__(self, adapters: list[SearchAdapter]) -> None:
        self._adapters = adapters

    def search(self, query: str, limit: int = 5) -> list[dict]:
        for adapter in self._adapters:
            try:
                results = adapter.search(query, limit=limit)
            except Exception as exc:
                import sys

                print(
                    f"[search] adapter={adapter.__class__.__name__} "
                    f"query={query[:50]!r} error={exc}",
                    file=sys.stderr,
                )
                continue
            if results:
                return results[:limit]
        return []


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
        max_chars: int | None = 2000,
    ) -> None:
        self._http_client = http_client or HttpClient()
        self._timeout = timeout
        self._max_chars = max_chars

    def run(self, args: dict) -> dict:
        url = str(args.get("url", "")).strip()
        if not url:
            raise ValueError("url is required")
        html_text = self._http_client.get_text(url, timeout=self._timeout)
        content = _clean_html_text(html_text)
        if self._max_chars is not None:
            content = content[: self._max_chars]
        return {
            "url": url,
            "title": _extract_title(html_text) or url,
            "content": content,
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
            if "content_ref" not in payload and hasattr(self._fetcher, "persist_payload"):
                payload = self._fetcher.persist_payload(payload)
                cache_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            payload["cached"] = True
            return payload
        payload = self._fetcher.run(args)
        payload["cached"] = False
        cache_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return payload


def _parse_duckduckgo_lite(html_text: str, limit: int) -> list[dict]:
    """Parse DuckDuckGo Lite / HTML results with flexible link extraction."""
    results: list[dict] = []

    # Find all external links with display text
    # Lite format: <a href="..." class="result-link">Title</a> near <span class="result-snippet">
    # HTML format: <a rel="nofollow" href="//duckduckgo.com/l/?uddg=...">Title</a>
    link_matches = list(re.finditer(
        r'<a\b[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        html_text,
        re.DOTALL | re.IGNORECASE,
    ))

    # Extract all possible snippet texts
    snippet_matches = []
    for pattern in [
        r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
        r'<span[^>]*class="[^"]*result-snippet[^"]*"[^>]*>(.*?)</span>',
        r'<span[^>]*class="[^"]*snippet[^"]*"[^>]*>(.*?)</span>',
        r'<td[^>]*class="[^"]*snippet[^"]*"[^>]*>(.*?)</td>',
        r'<div[^>]*class="[^"]*snippet[^"]*"[^>]*>(.*?)</div>',
    ]:
        snippet_matches = re.findall(pattern, html_text, re.DOTALL | re.IGNORECASE)
        if snippet_matches:
            break

    snippet_idx = 0
    seen_urls: set[str] = set()
    for match in link_matches:
        href = html.unescape(match.group("href"))
        title_raw = match.group("title")
        title = _strip_tags(title_raw).strip()

        # Skip non-result links (navigation, internal)
        if not title or len(title) < 3:
            continue
        if any(skip in href.lower() for skip in ("duckduckgo.com/settings", "duckduckgo.com/about",
                                                    "duckduckgo.com/privacy", "/html/", "/lite/",
                                                    "duckduckgo.com/newsletter")):
            continue

        url = _normalize_duckduckgo_url(href)
        if not url or "duckduckgo.com" in url:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        snippet = ""
        if snippet_idx < len(snippet_matches):
            snippet = _strip_tags(snippet_matches[snippet_idx]).strip()
            snippet_idx += 1

        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def _parse_duckduckgo_html(html_text: str, limit: int) -> list[dict]:
    """Fallback HTML parser — delegates to lite parser which handles both formats."""
    return _parse_duckduckgo_lite(html_text, limit)


def _parse_bing_html(html_text: str, limit: int) -> list[dict]:
    results: list[dict] = []
    seen_urls: set[str] = set()
    blocks = re.findall(
        r'<li\b[^>]*class="[^"]*\bb_algo\b[^"]*"[^>]*>(.*?)</li>',
        html_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not blocks:
        blocks = [html_text]

    for block in blocks:
        match = re.search(
            r'<h2[^>]*>\s*<a\b[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r'<a\b[^>]*href="(?P<href>https?://[^"]+)"[^>]*>(?P<title>.*?)</a>',
                block,
                re.DOTALL | re.IGNORECASE,
            )
        if not match:
            continue
        url = _normalize_bing_url(html.unescape(match.group("href")))
        title = _strip_tags(match.group("title"))
        if not title or not url.startswith(("http://", "https://")):
            continue
        if "bing.com" in parse.urlparse(url).netloc:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        snippet = ""
        snippet_match = re.search(
            r'<p\b[^>]*>(?P<snippet>.*?)</p>',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if snippet_match:
            snippet = _strip_tags(snippet_match.group("snippet"))

        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def _normalize_bing_url(href: str) -> str:
    parsed = parse.urlparse(href)
    if "bing.com" not in parsed.netloc:
        return href
    query = parse.parse_qs(parsed.query)
    encoded = query.get("u", [""])[0]
    if encoded.startswith("a1"):
        encoded = encoded[2:]
    if not encoded:
        return href
    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode((encoded + padding).encode()).decode()
    except Exception:
        return href
    return decoded if decoded.startswith(("http://", "https://")) else href


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


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)
