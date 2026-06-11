"""Real web search/fetch adapters built on standard-library HTTP."""

from __future__ import annotations

import hashlib
import html
import json
import random
import re
import ssl
import time
import base64
from pathlib import Path
from typing import Callable, Protocol
from urllib import parse, request as urllib_request


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
    """Bing HTML-search adapter with browser TLS fingerprint."""

    def __init__(
        self,
        http_client: HttpClient | BrowserHttpClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._http_client = http_client or BrowserHttpClient()
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


class BaiduSearch:
    """Baidu HTML-search adapter with browser TLS fingerprint."""

    def __init__(
        self,
        http_client: HttpClient | BrowserHttpClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._http_client = http_client or BrowserHttpClient()
        self._timeout = timeout

    def search(self, query: str, limit: int = 5) -> list[dict]:
        encoded = parse.quote_plus(query)
        try:
            html_text = self._http_client.get_text(
                f"https://www.baidu.com/s?wd={encoded}&rn={limit}",
                timeout=self._timeout,
            )
        except Exception as exc:
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
    ) -> None:
        self._http_client = http_client or BrowserHttpClient()
        self._timeout = timeout

    def search(self, query: str, limit: int = 5) -> list[dict]:
        encoded = parse.quote_plus(query)
        try:
            html_text = self._http_client.get_text(
                f"https://www.sogou.com/web?query={encoded}",
                timeout=self._timeout,
            )
        except Exception as exc:
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


class FallbackSearch:
    """Merge results from all search adapters, then deduplicate and rank.

    Queries every adapter (with a small delay between them) and merges
    results so the collector gets a diverse candidate pool instead of
    being locked into a single engine's ranking bias.
    """

    def __init__(self, adapters: list[SearchAdapter]) -> None:
        self._adapters = adapters

    def search(self, query: str, limit: int = 5) -> list[dict]:
        all_results: list[dict] = []
        seen_urls: set[str] = set()
        for adapter in self._adapters:
            time.sleep(random.uniform(0.3, 0.8))
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
            for r in results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)

        # Interleave results from different engines so the first N results
        # aren't dominated by a single engine.  Round-robin by original
        # position within each engine's result list.
        return _interleave(all_results, limit)


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
    """Interleave merged results by round-robin on original position.

    If DDG returns [A0, A1, A2] and Bing returns [B0, B1, B2],
    the output is [A0, B0, A1, B1, A2, B2] \u2014 so neither engine
    dominates the top of the list.
    """
    if not results:
        return []
    # Results arrive grouped by engine (DDG first, then Bing, etc).
    # Split into per-engine buckets, then interleave.
    seen_titles: set[str] = set()
    buckets: list[list[dict]] = []
    current_domain: str | None = None
    current_bucket: list[dict] = []

    for r in results:
        url = r.get("url", "")
        # Use top-level domain as engine proxy
        domain = parse.urlparse(url).netloc.split(".")[-2] if url else ""
        title_key = (r.get("title", "") or "")[:60]
        # Deduplicate across engines (same title likely same page)
        if title_key and title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        if domain != current_domain:
            if current_bucket:
                buckets.append(current_bucket)
            current_bucket = [r]
            current_domain = domain
        else:
            current_bucket.append(r)
    if current_bucket:
        buckets.append(current_bucket)

    # Round-robin across buckets
    output: list[dict] = []
    max_len = max(len(b) for b in buckets) if buckets else 0
    for i in range(max_len):
        for bucket in buckets:
            if i < len(bucket):
                output.append(bucket[i])
                if len(output) >= limit:
                    return output
    return output
