# 模块 34：搜索 API 主通道 + HTML fallback

## Goal

Stop relying on regex-parsed search-engine HTML as the only source of
truth for the collector. Page-structure changes used to silently zero
out results; now an API channel (Serper.dev) sits in front and the
HTML adapters become the safety net.

## Scope

In scope:

- New `SerperSearch` adapter and `SerperJsonTransport` (POST + JSON)
  in `runtime/web_tools.py`
- New `make_default_search_adapter()` factory that resolves
  `(provider, api_key)` → `SearchAdapter`
- `web/__init__.py` `_make_web_orchestrator` switches from a
  hardcoded HTML chain to the factory
- New env vars `CIA_SERPER_API_KEY` and `CIA_SEARCH_PROVIDER`
  (`auto` / `serper` / `html`)
- `config/.env.example` documents all CIA env entry points (model,
  search, timeout)
- Exports updated in `runtime/__init__.py`
- 5 unit tests in `tests/unit/test_real_web_tools.py`

Out of scope:

- Removing the HTML adapters (they remain as fallback)
- New API providers (SerpAPI / Brave) — the abstraction makes adding
  more providers trivial later
- Caching of Serper results (orthogonal to which adapter ran)
- Rate-limit / circuit-breaker logic — `FallbackSearch` already
  rotates on empty / error

## Design

### Adapter chain resolution

```
provider arg | env CIA_SEARCH_PROVIDER | env CIA_SERPER_API_KEY | resulting chain
"html"       | (any)                   | (any)                   | [DDG, Bing]
"serper"     | (any)                   | empty                   | [SerperSearch (inert)]
"serper"     | (any)                   | set                     | [SerperSearch]
None / "auto"| "html"                  | (any)                   | [DDG, Bing]
None / "auto"| "serper"                | empty                   | [SerperSearch (inert)]
None / "auto"| "serper"                | set                     | [SerperSearch]
None / "auto"| unset / "auto"          | empty                   | [DDG, Bing]
None / "auto"| unset / "auto"          | set                     | [SerperSearch, DDG, Bing]
```

The bottom-right cell is the production happy path. The bottom-left
cell preserves the prior keyless behavior verbatim.

### `SerperSearch` API contract

- **Auth**: `X-API-KEY` header from `api_key` constructor param or
  `CIA_SERPER_API_KEY` env var
- **Endpoint**: `https://google.serper.dev/search`
- **Request body**: `{q, num, gl, hl}` — `num` clamped to `[1, 10]`,
  `gl` defaults to `cn` for CJK queries else `us`, `hl` mirrors
  `gl`
- **Response parsing**: read `organic[].link`, `organic[].title`,
  `organic[].snippet`; skip items without `link` or `title`
- **Failure modes**: any HTTPError / URLError / OSError /
  TimeoutError / JSONDecodeError → log to stderr, return `[]`
- **Keyless mode**: no network call, return `[]`

### `SerperJsonTransport`

Minimal stdlib POST + JSON client. Kept distinct from
`runtime.model_runtime.JsonPostTransport` to avoid pulling provider
error classes into the search namespace. Tests inject
`StubSerperTransport`.

## Tests

`tests/unit/test_real_web_tools.py`:

1. `test_serper_search_parses_organic_results` — stub returns 2-item
   organic array; asserts shape, X-API-KEY header, payload
2. `test_serper_search_returns_empty_on_transport_error` — stub
   raises `OSError`; asserts `[]`
3. `test_serper_search_is_inert_without_api_key` — empty key + stub
   that records calls; asserts no network call and `[]`
4. `test_make_default_search_adapter_prefers_serper_when_keyed` —
   env-set key; asserts SerperSearch first, DDG still in chain
5. `test_make_default_search_adapter_keyless_keeps_html_only` — no
   key; asserts no SerperSearch in chain, DDG present

Tests stub `BrowserHttpClient` via monkeypatch because the real class
imports `curl_cffi` at construction time (optional dependency).

## Backward compatibility

- Existing tests untouched; `BingSearch` / `DuckDuckGoSearch` / etc.
  still imported from the same module
- Keyless production runs (`CIA_SERPER_API_KEY` unset) get the same
  `FallbackSearch([DDG, Bing])` chain as before
- The hardcoded `WebSearchTool(FallbackSearch([DDG, Bing]))` line in
  `_make_web_orchestrator` is replaced by
  `WebSearchTool(make_default_search_adapter())` — equivalent when
  unkeyed, Serper-led when keyed

## Related

- [[32-model-retry]] — adopts the same "transport layer raises typed
  errors" pattern; SerperSearch's inline error catching is a simpler
  variant because failures here only need to be downgraded to `[]`
- [[33-global-timeout]] — both modules surface env-var configuration
  (`CIA_SERPER_API_KEY` / `CIA_SEARCH_PROVIDER` / `CIA_MAX_RUN_SECONDS`);
  documented together in `config/.env.example`
