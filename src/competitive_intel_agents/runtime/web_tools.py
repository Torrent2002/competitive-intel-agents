"""Real web search/fetch adapters built on standard-library HTTP."""

from __future__ import annotations

import hashlib
import html
import json
import os
import random
import re
import ssl
import time
import base64
from pathlib import Path
from typing import Callable, Protocol
from urllib import error as urllib_error, parse, request as urllib_request

from .rate_limiter import TokenBucket


def _looks_like_429(error_text: str) -> bool:
    """Heuristic: detect ``HTTP 429`` markers in opaque error strings.

    HTML adapters wrap ``urllib`` / ``curl_cffi`` exceptions in a generic
    ``RuntimeError("failed to fetch …: <inner>")``, so the only way to
    react to rate-limit responses without changing the HTTP-client
    contract is to inspect the error text.
    """
    s = error_text.lower()
    return "429" in s or "too many requests" in s


def _get_ssl_context() -> ssl.SSLContext:
    """Return SSLContext with a known-good CA bundle.

    Self-contained — does not depend on environment variables or
    the Python distribution's compiled-in OpenSSL paths.
    """
    # certifi ships its own Mozilla CA bundle and works everywhere.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass

    # Fall back to well-known system paths.
    for cert_path in (
        "/etc/ssl/cert.pem",
        "/etc/ssl/certs/ca-certificates.crt",
        "/opt/homebrew/etc/openssl@3/cert.pem",
        "/usr/local/etc/openssl@3/cert.pem",
    ):
        if Path(cert_path).exists():
            return ssl.create_default_context(cafile=cert_path)

    # Last resort.
    return ssl.create_default_context()


_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class SearchAdapter(Protocol):
    def search(self, query: str, limit: int = 5) -> list[dict]:
        ...


def _default_opener() -> Callable:
    https_handler = urllib_request.HTTPSHandler(context=_get_ssl_context())
    return urllib_request.build_opener(https_handler).open


class HttpClient:
    """Small HTTP client wrapper so tests can inject transports."""

    def __init__(self, opener: Callable | None = None) -> None:
        self._opener = opener or _default_opener()

    def get_text(self, url: str, timeout: float = 10.0, headers: dict | None = None) -> str:
        merged = {
            "User-Agent": "competitive-intel-agents/0.1 (+local research tool)",
        }
        if headers:
            merged.update(headers)
        req = urllib_request.Request(url, headers=merged)
        try:
            with self._opener(req, timeout=timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except Exception as exc:
            raise RuntimeError(f"failed to fetch {url}: {exc}") from exc


class BrowserHttpClient:
    """HTTP client backed by curl_cffi — mimics Chrome TLS fingerprint.

    urllib + OpenSSL has a distinct JA4 fingerprint that anti-bot systems
    detect on the very first request.  curl_cffi wraps curl-impersonate
    which uses BoringSSL patches to match Chrome's TLS handshake exactly.
    """

    def __init__(self) -> None:
        from curl_cffi import requests as curl_requests

        self._requests = curl_requests

    def get_text(self, url: str, timeout: float = 10.0, headers: dict | None = None) -> str:
        merged = {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
        if headers:
            merged.update(headers)
        try:
            resp = self._requests.get(
                url,
                impersonate="chrome124",
                headers=merged,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            raise RuntimeError(f"failed to fetch {url}: {exc}") from exc


class DuckDuckGoSearch:
    """HTML-search adapter for optional real local collection."""

    def __init__(
        self,
        http_client: HttpClient | None = None,
        timeout: float = 10.0,
        rate_limiter: TokenBucket | None = None,
    ) -> None:
        self._http_client = http_client or HttpClient()
        self._timeout = timeout
        self._rate_limiter = rate_limiter

    def search(self, query: str, limit: int = 5) -> list[dict]:
        if self._rate_limiter is not None:
            self._rate_limiter.acquire()
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
            if self._rate_limiter is not None and _looks_like_429(str(exc)):
                self._rate_limiter.penalize()
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
                if self._rate_limiter is not None and _looks_like_429(str(exc)):
                    self._rate_limiter.penalize()
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
    """Bing HTML-search adapter with browser TLS fingerprint."""

    def __init__(
        self,
        http_client: HttpClient | BrowserHttpClient | None = None,
        timeout: float = 10.0,
        rate_limiter: TokenBucket | None = None,
    ) -> None:
        self._http_client = http_client or BrowserHttpClient()
        self._timeout = timeout
        self._rate_limiter = rate_limiter

    def search(self, query: str, limit: int = 5) -> list[dict]:
        if self._rate_limiter is not None:
            self._rate_limiter.acquire()
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
            if self._rate_limiter is not None and _looks_like_429(str(exc)):
                self._rate_limiter.penalize()
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


class BaiduSearch:
    """Baidu HTML-search adapter with browser TLS fingerprint."""

    def __init__(
        self,
        http_client: HttpClient | BrowserHttpClient | None = None,
        timeout: float = 10.0,
        rate_limiter: TokenBucket | None = None,
    ) -> None:
        self._http_client = http_client or BrowserHttpClient()
        self._timeout = timeout
        self._rate_limiter = rate_limiter

    def search(self, query: str, limit: int = 5) -> list[dict]:
        if self._rate_limiter is not None:
            self._rate_limiter.acquire()
        encoded = parse.quote_plus(query)
        try:
            html_text = self._http_client.get_text(
                f"https://www.baidu.com/s?wd={encoded}&rn={limit}",
                timeout=self._timeout,
            )
        except Exception as exc:
            if self._rate_limiter is not None and _looks_like_429(str(exc)):
                self._rate_limiter.penalize()
            import sys

            print(
                f"[baidu] query={query[:50]!r} results=0 error={exc}",
                file=sys.stderr,
            )
            return []
        results = _parse_baidu_html(html_text, limit)
        if not results:
            import sys

            print(
                f"[baidu] query={query[:50]!r} results=0 parsed_empty(len={len(html_text)})",
                file=sys.stderr,
            )
        return results


class SogouSearch:
    """Sogou HTML-search adapter with browser TLS fingerprint."""

    def __init__(
        self,
        http_client: HttpClient | BrowserHttpClient | None = None,
        timeout: float = 10.0,
        rate_limiter: TokenBucket | None = None,
    ) -> None:
        self._http_client = http_client or BrowserHttpClient()
        self._timeout = timeout
        self._rate_limiter = rate_limiter

    def search(self, query: str, limit: int = 5) -> list[dict]:
        if self._rate_limiter is not None:
            self._rate_limiter.acquire()
        encoded = parse.quote_plus(query)
        try:
            html_text = self._http_client.get_text(
                f"https://www.sogou.com/web?query={encoded}",
                timeout=self._timeout,
            )
        except Exception as exc:
            if self._rate_limiter is not None and _looks_like_429(str(exc)):
                self._rate_limiter.penalize()
            import sys

            print(
                f"[sogou] query={query[:50]!r} results=0 error={exc}",
                file=sys.stderr,
            )
            return []
        results = _parse_sogou_html(html_text, limit)
        if not results:
            import sys

            print(
                f"[sogou] query={query[:50]!r} results=0 parsed_empty(len={len(html_text)})",
                file=sys.stderr,
            )
        return results


class SerperJsonTransport:
    """Minimal POST+JSON client for the Serper.dev search API.

    Kept separate from ``HttpClient`` (GET) and ``BrowserHttpClient``
    (TLS-fingerprinted GET via curl_cffi) because Serper expects a
    plain HTTPS POST with an ``X-API-KEY`` header — no browser
    impersonation needed and no HTML parsing involved.
    """

    def __init__(self) -> None:
        self._ssl_context = _get_ssl_context()

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        timeout: float,
    ) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=timeout, context=self._ssl_context) as response:
            return json.loads(response.read().decode("utf-8"))


class SerperSearch:
    """Serper.dev API adapter — Google results without HTML scraping.

    Reads ``CIA_SERPER_API_KEY`` from the environment if no key is
    passed explicitly. When the key is missing the adapter is inert
    (returns ``[]``) so it can sit at the front of a fallback chain
    without breaking unauthenticated runs.
    """

    SERPER_ENDPOINT = "https://google.serper.dev/search"

    def __init__(
        self,
        api_key: str | None = None,
        transport: SerperJsonTransport | None = None,
        timeout: float = 8.0,
        region: str | None = None,
        rate_limiter: TokenBucket | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get(
            "CIA_SERPER_API_KEY", ""
        ).strip()
        self._transport = transport or SerperJsonTransport()
        self._timeout = timeout
        # Region pinning is optional — Serper auto-detects from the
        # query language if omitted, but explicit pinning makes the
        # tier-1 result set more predictable for CJK queries.
        self._region = region
        self._rate_limiter = rate_limiter

    def search(self, query: str, limit: int = 5) -> list[dict]:
        if not self._api_key:
            # Quietly inert — the fallback chain falls through to
            # HTML adapters so existing key-less setups still work.
            return []
        if self._rate_limiter is not None:
            self._rate_limiter.acquire()
        region = self._region or ("cn" if _contains_cjk(query) else "us")
        language = "zh-cn" if region == "cn" else "en"
        payload = {
            "q": query,
            "num": max(1, min(limit, 10)),
            "gl": region,
            "hl": language,
        }
        try:
            raw = self._transport.post_json(
                self.SERPER_ENDPOINT,
                headers={"X-API-KEY": self._api_key},
                payload=payload,
                timeout=self._timeout,
            )
        except urllib_error.HTTPError as exc:
            # 429 from Serper: respect the rate limit. The fallback
            # chain will move on to HTML adapters without retrying
            # Serper for the rest of this run's penalty window.
            if exc.code == 429 and self._rate_limiter is not None:
                self._rate_limiter.penalize()
            import sys

            print(
                f"[serper] query={query[:50]!r} results=0 error={exc}",
                file=sys.stderr,
            )
            return []
        except (urllib_error.URLError, OSError, TimeoutError) as exc:
            import sys

            print(
                f"[serper] query={query[:50]!r} results=0 error={exc}",
                file=sys.stderr,
            )
            return []
        except json.JSONDecodeError as exc:
            import sys

            print(
                f"[serper] query={query[:50]!r} results=0 invalid_json={exc}",
                file=sys.stderr,
            )
            return []

        organic = raw.get("organic") if isinstance(raw, dict) else None
        if not isinstance(organic, list):
            import sys

            print(
                f"[serper] query={query[:50]!r} results=0 no_organic_key",
                file=sys.stderr,
            )
            return []
        results: list[dict] = []
        for item in organic[:limit]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link", "")).strip()
            title = str(item.get("title", "")).strip()
            snippet = str(item.get("snippet", "")).strip()
            if not url or not title:
                continue
            results.append({"url": url, "title": title, "snippet": snippet})
        return results


class FallbackSearch:
    """Merge results from all search adapters, then deduplicate and rank.

    Each adapter is responsible for its own rate limiting (via an
    injected :class:`TokenBucket`), so this class no longer inserts a
    ``time.sleep`` between adapters — the previous random-jitter delay
    was a coarse stand-in for the per-engine throttling that now lives
    inside each adapter.
    """

    def __init__(self, adapters: list[SearchAdapter]) -> None:
        self._adapters = adapters

    def search(self, query: str, limit: int = 5) -> list[dict]:
        all_results: list[dict] = []
        seen_urls: set[str] = set()
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
            engine_name = adapter.__class__.__name__
            for r in results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    # Tag each result with the engine that produced it so
                    # _interleave can bucket by source engine rather than
                    # by adjacent-domain heuristic (which degenerates to
                    # singleton buckets when an engine returns results
                    # spanning multiple domains).
                    tagged = dict(r)
                    tagged.setdefault("_engine", engine_name)
                    all_results.append(tagged)

        # Interleave results from different engines so the first N results
        # aren't dominated by a single engine.  Round-robin by original
        # position within each engine's result list.
        return _interleave(all_results, limit)


def _default_search_rate_limiters() -> dict[str, TokenBucket]:
    """Per-engine token buckets used by ``make_default_search_adapter``.

    Rates are tuned conservatively for unauthenticated public endpoints:
    DuckDuckGo tolerates roughly 1 rps before its bot wall kicks in,
    Bing/Baidu/Sogou are stricter so cap at 0.5 rps. Serper has a
    documented per-second quota but the API limits via 429 — the
    bucket is mainly here so ``penalize`` has a place to land when a
    429 happens.
    """
    return {
        "ddg": TokenBucket(rate_per_sec=1.0, burst=2),
        "bing": TokenBucket(rate_per_sec=0.5, burst=1),
        "baidu": TokenBucket(rate_per_sec=0.5, burst=1),
        "sogou": TokenBucket(rate_per_sec=0.5, burst=1),
        "serper": TokenBucket(rate_per_sec=10.0, burst=5),
    }


def make_default_search_adapter(
    provider: str | None = None,
    serper_api_key: str | None = None,
    rate_limiters: dict[str, TokenBucket] | None = None,
) -> SearchAdapter:
    """Build the default ``SearchAdapter`` for the orchestrator.

    Resolution order:

    - ``provider`` argument (``"serper"`` / ``"html"`` / ``"auto"``) wins
      if passed
    - else ``CIA_SEARCH_PROVIDER`` env var
    - else ``"auto"`` — picks Serper-led fallback when a key is
      available, pure-HTML fallback otherwise

    The HTML adapters stay in the chain even when Serper is the
    primary so the tool keeps producing results when the API quota is
    exhausted or the key gets revoked. Serper sits in front because
    its results are the most stable and don't depend on regex parsing
    of any HTML page.

    Each adapter receives a per-engine ``TokenBucket`` so a noisy
    adapter cannot DoS the others. ``rate_limiters`` lets tests
    inject deterministic buckets; production callers should leave it
    ``None`` to get the safe defaults from
    :func:`_default_search_rate_limiters`.
    """
    chosen = (provider or os.environ.get("CIA_SEARCH_PROVIDER", "")).strip().lower() or "auto"
    api_key = (
        serper_api_key
        if serper_api_key is not None
        else os.environ.get("CIA_SERPER_API_KEY", "").strip()
    )
    limiters = rate_limiters if rate_limiters is not None else _default_search_rate_limiters()

    # Build adapters lazily per branch.  ``BingSearch()`` instantiates
    # ``BrowserHttpClient`` which imports ``curl_cffi`` at __init__
    # time, so eagerly constructing it for every branch would raise
    # ``ImportError`` on hosts that only need the Serper path and have
    # not installed the optional binary dependency. The branches below
    # only build the adapters they actually return.
    if chosen == "html":
        return FallbackSearch(
            [
                DuckDuckGoSearch(timeout=8, rate_limiter=limiters.get("ddg")),
                BingSearch(rate_limiter=limiters.get("bing")),
            ]
        )
    if chosen == "serper":
        # Serper-only mode is opt-in for tightly-budgeted quotas where
        # HTML fallback shouldn't kick in even on Serper failure.
        return FallbackSearch(
            [SerperSearch(api_key=api_key, rate_limiter=limiters.get("serper"))]
        )
    # "auto" (default): prefer Serper when keyed; otherwise behave
    # exactly as before — HTML adapters only.
    if api_key:
        return FallbackSearch(
            [
                SerperSearch(api_key=api_key, rate_limiter=limiters.get("serper")),
                DuckDuckGoSearch(timeout=8, rate_limiter=limiters.get("ddg")),
                BingSearch(rate_limiter=limiters.get("bing")),
            ]
        )
    return FallbackSearch(
        [
            DuckDuckGoSearch(timeout=8, rate_limiter=limiters.get("ddg")),
            BingSearch(rate_limiter=limiters.get("bing")),
        ]
    )


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
        domain_rate_limiters: dict[str, TokenBucket] | None = None,
        default_domain_rate: float = 0.5,
    ) -> None:
        self._http_client = http_client or HttpClient()
        self._timeout = timeout
        self._max_chars = max_chars
        # Pre-seeded buckets the caller wants pinned to specific rates
        # (e.g. faster/slower than the default). Per-domain buckets for
        # any other host are created on demand the first time we see
        # the host, so each unique domain ends up with its own bucket.
        self._domain_limiters: dict[str, TokenBucket] = (
            dict(domain_rate_limiters) if domain_rate_limiters else {}
        )
        self._default_domain_rate = default_domain_rate

    def _limiter_for(self, host: str) -> TokenBucket:
        bucket = self._domain_limiters.get(host)
        if bucket is None:
            bucket = TokenBucket(rate_per_sec=self._default_domain_rate, burst=1)
            self._domain_limiters[host] = bucket
        return bucket

    def run(self, args: dict) -> dict:
        url = str(args.get("url", "")).strip()
        if not url:
            raise ValueError("url is required")
        host = parse.urlparse(url).hostname or ""
        if host:
            self._limiter_for(host).acquire()
        try:
            html_text = self._http_client.get_text(url, timeout=self._timeout)
        except Exception as exc:
            if host and _looks_like_429(str(exc)):
                self._limiter_for(host).penalize()
            raise
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


def _parse_baidu_html(html_text: str, limit: int) -> list[dict]:
    results: list[dict] = []
    seen_urls: set[str] = set()
    blocks = re.findall(
        r'<div\b[^>]*class="[^"]*result[^"]*c-container[^"]*"[^>]*>(.*?)'
        r"(?=<div\b[^>]*class=\"[^\"]*result|\Z)",
        html_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not blocks:
        blocks = re.findall(
            r'<div\b[^>]*class="[^"]*c-container[^"]*"[^>]*>(.*?)'
            r"(?=<div\b[^>]*class=\"[^\"]*c-container|\Z)",
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
    if not blocks:
        blocks = [html_text]

    for block in blocks:
        match = re.search(
            r'<a\b[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if not match:
            continue
        href = html.unescape(match.group("href"))
        title = _strip_tags(match.group("title"))
        if not title:
            continue

        real_url = _normalize_baidu_url(href)
        if not real_url.startswith(("http://", "https://")):
            continue
        if real_url in seen_urls:
            continue
        seen_urls.add(real_url)

        snippet = ""
        snippet_match = re.search(
            r'<(?:span|div)\b[^>]*class="[^"]*c-abstract[^"]*"[^>]*>(?P<snippet>.*?)</(?:span|div)>',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if not snippet_match:
            snippet_match = re.search(
                r'<(?:span|div)\b[^>]*class="[^"]*content[^"]*"[^>]*>(?P<snippet>.*?)</(?:span|div)>',
                block,
                re.DOTALL | re.IGNORECASE,
            )
        if snippet_match:
            snippet = _strip_tags(snippet_match.group("snippet"))

        results.append({"title": title, "url": real_url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def _normalize_baidu_url(href: str) -> str:
    if href.startswith(("http://", "https://")) and "baidu.com" not in parse.urlparse(href).netloc:
        return href
    if not href.startswith(("http://", "https://")):
        if href.startswith("//"):
            href = "https:" + href
        else:
            return href
    parsed = parse.urlparse(href)
    query = parse.parse_qs(parsed.query)
    encoded = query.get("url", [""])[0]
    if not encoded:
        realurl = query.get("realurl", [""])[0]
        if realurl:
            return realurl
        return href
    if encoded.startswith(("http://", "https://")):
        return encoded
    try:
        decoded = parse.unquote(encoded)
        if decoded.startswith(("http://", "https://")):
            return decoded
    except Exception:
        pass
    return href


def _parse_sogou_html(html_text: str, limit: int) -> list[dict]:
    results: list[dict] = []
    seen_urls: set[str] = set()
    blocks = re.findall(
        r'<div\b[^>]*class="[^"]*vrwrap[^"]*"[^>]*>(.*?)'
        r"(?=<div\b[^>]*class=\"[^\"]*vrwrap|\Z)",
        html_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not blocks:
        blocks = re.findall(
            r'<div\b[^>]*class="[^"]*rb\b[^"]*"[^>]*>(.*?)'
            r"(?=<div\b[^>]*class=\"[^\"]*rb\b|\Z)",
            html_text,
            re.DOTALL | re.IGNORECASE,
        )

    for block in blocks:
        match = re.search(
            r'<a\b[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if not match:
            continue
        href = html.unescape(match.group("href"))
        title = _strip_tags(match.group("title"))
        if not title:
            continue

        # Sogou now puts the real URL in data-url elsewhere in the block;
        # the href carries an encrypted redirect we can't decode.
        data_url_match = re.search(
            r'data-url="(?P<url>https?://[^"]+)"',
            block,
            re.IGNORECASE,
        )
        if data_url_match:
            real_url = data_url_match.group("url")
        else:
            real_url = _normalize_sogou_url(href)

        if not real_url.startswith(("http://", "https://")):
            continue
        if "sogou.com" in parse.urlparse(real_url).netloc:
            continue
        if real_url in seen_urls:
            continue
        seen_urls.add(real_url)

        snippet = ""
        snippet_match = re.search(
            r'<(?:div|p)\b[^>]*class="[^"]*(?:space-txt|str-text|abstract)[^"]*"[^>]*>(?P<snippet>.*?)</(?:div|p)>',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if snippet_match:
            snippet = _strip_tags(snippet_match.group("snippet"))

        results.append({"title": title, "url": real_url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def _normalize_sogou_url(href: str) -> str:
    if href.startswith(("http://", "https://")) and "sogou.com" not in parse.urlparse(href).netloc:
        return href
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("/"):
        href = f"https://www.sogou.com{href}"
    parsed = parse.urlparse(href)
    query = parse.parse_qs(parsed.query)
    encoded = query.get("url", [""])[0]
    if not encoded:
        return href
    try:
        decoded = parse.unquote(encoded)
        if decoded.startswith(("http://", "https://")):
            return decoded
    except Exception:
        pass
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


def _interleave(results: list[dict], limit: int) -> list[dict]:
    """Interleave merged results by round-robin on source engine.

    If DDG returns [A0, A1, A2] and Bing returns [B0, B1, B2],
    the output is [A0, B0, A1, B1, A2, B2] \u2014 so neither engine
    dominates the top of the list.

    Buckets are formed by the result's ``_engine`` tag (set by
    FallbackSearch.search). When the tag is missing \u2014 e.g. results
    from an older code path \u2014 we fall back to bucketing by adjacent
    same-domain runs, preserving previous behaviour.
    """
    if not results:
        return []
    seen_titles: set[str] = set()
    buckets_by_engine: dict[str, list[dict]] = {}
    bucket_order: list[str] = []
    legacy_buckets: list[list[dict]] = []
    legacy_current_domain: str | None = None
    legacy_current_bucket: list[dict] = []

    for r in results:
        url = r.get("url", "")
        title_key = (r.get("title", "") or "")[:60]
        # Deduplicate across engines (same title likely same page)
        if title_key and title_key in seen_titles:
            continue
        if title_key:
            seen_titles.add(title_key)

        engine = r.get("_engine")
        if engine:
            if engine not in buckets_by_engine:
                buckets_by_engine[engine] = []
                bucket_order.append(engine)
            buckets_by_engine[engine].append(r)
            continue

        # Legacy path: bucket by adjacent same-domain runs.
        domain = parse.urlparse(url).netloc.split(".")[-2] if url else ""
        if domain != legacy_current_domain:
            if legacy_current_bucket:
                legacy_buckets.append(legacy_current_bucket)
            legacy_current_bucket = [r]
            legacy_current_domain = domain
        else:
            legacy_current_bucket.append(r)
    if legacy_current_bucket:
        legacy_buckets.append(legacy_current_bucket)

    buckets = [buckets_by_engine[name] for name in bucket_order] + legacy_buckets

    # Round-robin across buckets. Strip the internal ``_engine`` tag on
    # the way out so consumers see the same shape FallbackSearch has
    # always produced.
    output: list[dict] = []
    max_len = max(len(b) for b in buckets) if buckets else 0
    for i in range(max_len):
        for bucket in buckets:
            if i < len(bucket):
                item = bucket[i]
                if "_engine" in item:
                    item = {k: v for k, v in item.items() if k != "_engine"}
                output.append(item)
                if len(output) >= limit:
                    return output
    return output
