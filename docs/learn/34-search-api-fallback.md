# 学习文档 34：搜索 API 化 — Serper 主通道 + HTML fallback

## 一句话概括

**新增 `SerperSearch` 通过 Google 的官方 API 获取稳定结果，作为 `FallbackSearch` 链的首选；DDG/Bing 等 HTML 解析适配器降级为 fallback —— 搜索引擎页面改版不再静默把 collector 拖到零产出。**

## 为什么需要它

### 触发改动的真实场景

之前的搜索链：

```
FallbackSearch([
    DuckDuckGoSearch(),    # 解析 DDG html
    BingSearch(),          # 解析 Bing html
    BaiduSearch(),         # 解析 Baidu html
    SogouSearch(),         # 解析 Sogou html
])
```

每个 adapter 用大量正则匹配 HTML 结构。系统已经被这种脆弱性多次打过：

- Sogou 加 CAPTCHA → 整站 0 结果
- Bing 改 result block class 名 → `_parse_bing_html` 返回空
- DDG 把 lite 版结构改了几次 → 我们补丁追了 5 个 snippet 模式

最糟的是：**正则失败时返回空列表**，外层不知道是"没结果"还是"解析挂了"，collector 就以为这个 query 真没结果，继续往下走。最后产出 `[]`，整个 run 拿不到 source。

### 为什么不直接抛弃 HTML 解析

考虑过纯切到 API。否决理由：

1. **额度受限**：Serper 免费层 2500 次/月，演示/教学/CI 跑得快就用光了
2. **零依赖能跑**：项目要保持"开箱不需要外部账户也能本地跑"
3. **API 也会挂**：5xx、配额耗尽、key 被吊销 — HTML 是真兜底

所以采用 **API 主通道 + HTML 降级**：

```
有 CIA_SERPER_API_KEY:
    FallbackSearch([SerperSearch(), DuckDuckGoSearch(), BingSearch()])
        ↑                              ↑
        优先 (稳定)                    兜底 (脆弱但免费)

无 key:
    FallbackSearch([DuckDuckGoSearch(), BingSearch()])
        # 行为跟改动前完全一致
```

API 平时挑大梁，HTML 在 API 挂时才上场。两边互为对方的安全网。

### 为什么选 Serper.dev

候选方案对比：

| 方案 | 月度免费 | 稳定性 | 数据源 | 国内可访问 |
|------|----------|--------|--------|------------|
| Serper.dev | 2500 | ⭐⭐⭐⭐ | Google | ✅ |
| SerpAPI | 100 | ⭐⭐⭐⭐⭐ | 多家 | ✅ |
| Brave Search | 2000 | ⭐⭐⭐ | 自建索引 | ⚠️ |
| Google CSE | 100 | ⭐⭐⭐⭐ | Google | ⚠️ |

Serper：

- 免费额度足够开发期使用
- POST + JSON 直来直去，30 行代码搞定
- 直接 Google 结果，竞品分析类 query 召回好
- pricing 友好，付费层 $50 / 50k queries

## 关键代码

```python
# src/competitive_intel_agents/runtime/web_tools.py

class SerperSearch:
    SERPER_ENDPOINT = "https://google.serper.dev/search"

    def __init__(self, api_key=None, transport=None, timeout=8.0, region=None):
        self._api_key = api_key if api_key is not None else os.environ.get(
            "CIA_SERPER_API_KEY", ""
        ).strip()
        self._transport = transport or SerperJsonTransport()
        self._timeout = timeout
        self._region = region

    def search(self, query, limit=5):
        if not self._api_key:
            return []   # 空 key → 静默不调网络，让 fallback 接管
        region = self._region or ("cn" if _contains_cjk(query) else "us")
        payload = {"q": query, "num": ..., "gl": region, "hl": ...}
        try:
            raw = self._transport.post_json(self.SERPER_ENDPOINT, ...)
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            print(f"[serper] error={exc}", file=sys.stderr)
            return []
        organic = raw.get("organic")
        return [
            {"url": item["link"], "title": item["title"], "snippet": item.get("snippet", "")}
            for item in organic[:limit]
            if item.get("link") and item.get("title")
        ]


def make_default_search_adapter(provider=None, serper_api_key=None) -> SearchAdapter:
    chosen = (provider or os.environ.get("CIA_SEARCH_PROVIDER", "")).strip().lower() or "auto"
    api_key = serper_api_key if serper_api_key is not None else os.environ.get("CIA_SERPER_API_KEY", "").strip()
    html_chain = [DuckDuckGoSearch(timeout=8), BingSearch()]

    if chosen == "html":
        return FallbackSearch(html_chain)
    if chosen == "serper":
        return FallbackSearch([SerperSearch(api_key=api_key)])
    if api_key:
        return FallbackSearch([SerperSearch(api_key=api_key), *html_chain])
    return FallbackSearch(html_chain)
```

## 设计取舍

### 为什么没有 key 时 `SerperSearch` 静默返回 `[]` 而不是抛错

主流做法是抛 `MissingApiKeyError`。这里反过来：**没 key 时静默不动**。理由：

`make_default_search_adapter` 已经在工厂层判断 key 决定要不要把 SerperSearch 放进链。但万一调用方（测试 / 用户脚本）直接构造 `SerperSearch()` 又没 key，最不让人意外的行为是"等同于一个空结果适配器"，让 fallback 接管。

抛错的话调用方就要写 try/except 包一层；返回空成本最低。

### 为什么把 region 拆出来而不是让用户传完整 query 参数

```python
region = self._region or ("cn" if _contains_cjk(query) else "us")
```

CJK 自动用 `gl=cn`，否则 `gl=us`。这是经验值——竞品分析里"飞书 vs 钉钉"用 us locale 召回会偏，"Notion vs Coda"用 cn locale 也会偏。用户可以显式传 `region=` 覆盖。

更精巧的方案是按 query 内容判断（比如"飞书 in English market"）但那是 over-engineering。CJK 启发法 cover 了 95% 的真实流量。

### 为什么 transport 抽出来注入

```python
class SerperJsonTransport:
    def post_json(self, url, headers, payload, timeout): ...

class SerperSearch:
    def __init__(self, ..., transport=None):
        self._transport = transport or SerperJsonTransport()
```

测试用 `StubSerperTransport({"organic": [...]})` 注入，零网络 IO。生产代码用默认。这跟 `JsonPostTransport` / `HttpClient` / `BrowserHttpClient` 的注入模式一致——本项目已经形成了"传输层都做依赖注入"的约定。

### 为什么不直接复用 `JsonPostTransport`（model_runtime 的）

`JsonPostTransport.post_json` 现在抛 `RetryableProviderError` / `NonRetryableProviderError`（[[32-model-retry]] 引入）。把它给 SerperSearch 用就要：

- SerperSearch 还得 import 那两个错误类型来 except
- 跨模块耦合：搜索失败的语义不应该叫 "provider error"
- 重试策略不一样：model 调用值得重试 3 次，搜索失败直接降级到 fallback 更好

所以同样的 30 行 `urllib_request.urlopen + json.dumps`，做成 `SerperJsonTransport` 自己拥有。代价是几行重复，收益是边界清晰。

### 为什么 `FallbackSearch` 不动

`FallbackSearch` 已经有：

- 按 adapter 顺序调用
- 单 adapter 抛错时 print 日志、继续下一个
- 用 `_engine` tag round-robin 各源结果
- 去重（按 URL）
- 截断到 limit

这些跟"具体哪个 adapter 是 API 的"完全正交。新加 `SerperSearch` 只是往 list 里 push 一个，`FallbackSearch._interleave` 把它视为又一个 engine，走同一套 round-robin。**好抽象的表现就是新功能不需要碰旧代码**。

### `CIA_SEARCH_PROVIDER=serper` 模式存在的意义

正常用 `auto`：有 key 就 Serper-led，没 key 就 HTML-only。

`serper-only` 是给 quota 紧的场景：你买了 5k/月 的额度但不想被 HTML fallback 偷偷打掉额度（比如被 IP 封了 DDG，每次都走到 Serper），就显式 `serper-only`，Serper 挂了直接报 0 结果让上游决定，不假装"我兜底了"。

`html-only` 是 escape hatch：发现 Serper 给的结果质量异常差时，临时关掉。

## 测试

`tests/unit/test_real_web_tools.py` 加了 5 个新测试：

1. `test_serper_search_parses_organic_results` — stub transport 返回 organic array，断言 url/title/snippet 提取正确，header 含 X-API-KEY，payload 含 query
2. `test_serper_search_returns_empty_on_transport_error` — stub transport 抛 OSError，断言返回 `[]` 不抛
3. `test_serper_search_is_inert_without_api_key` — 空 key + stub transport，断言不发请求且返回 `[]`
4. `test_make_default_search_adapter_prefers_serper_when_keyed` — env 带 key，断言 adapter 链首位是 SerperSearch + 还含 DDG
5. `test_make_default_search_adapter_keyless_keeps_html_only` — 无 key，断言链里没 SerperSearch、保留 DDG —— 跟改动前完全一致

## 面试要点

1. **API + HTML 两条腿走路**：纯 API 受额度/key 牵制，纯 HTML 受页面改版牵制；让两者互为对方的兜底
2. **静默空 vs 抛错**：搜索 adapter 链上"空结果"语义和"抛错"语义都被 FallbackSearch 同样处理（继续下一个 adapter），所以 SerperSearch 没 key 直接返回 `[]` 比抛 missing-key 错更省心
3. **region 启发式而不是配置**：CJK 自动 `gl=cn`，覆盖 95% case；其余允许 `region=` 显式传 — 启发式不该比真实使用场景复杂
4. **不要勉强复用 transport**：明明可以共享 `JsonPostTransport`，但跨语义的耦合最终是债务（不同的错误类型、不同的重试策略），保留一个独立的 30 行 transport 反而干净
5. **工厂函数承载策略**：`make_default_search_adapter` 一个函数把 `provider` × `api_key` 的 4 种组合（auto/serper/html × 有 key/无 key）抽成 3-行决策树；调用方拿到的就是一个 SearchAdapter，无需关心选了哪条
6. **跟 [[32-model-retry]] 的对比**：model 调用值得重试因为单次失败成本高（agent 整轮重跑），搜索失败成本低（fallback 链兜底），所以这里不加重试，直接降级
