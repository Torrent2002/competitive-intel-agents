# 模块 21：真实 Web 采集工具

## 目标

在不破坏 fake 模式确定性的前提下，为 Collector 提供可选的真实 Web 信息采集能力。v1a 的重点不是大规模爬虫，而是把“搜索、抓取、缓存、工具隔离”这条链路接成可替换的运行时边界。

## 当前实现

- `HttpClient`
  - 基于标准库 `urllib`，统一设置 User-Agent。
  - 对外只暴露 `get_text(url, timeout)`，便于测试注入 fake opener。
  - 网络异常会转成 `RuntimeError`，由 `ToolRuntime` 进入工具错误路径。
- `DuckDuckGoSearch`
  - 使用 DuckDuckGo HTML 搜索页作为本地可选搜索适配器。
  - 只负责把搜索 HTML 解析成 `title/url/snippet`。
- `WebSearchTool`
  - `ToolRuntime` 兼容工具，名称为 `web_search`。
  - 接收 `query` 和可选 `limit`。
  - 适配器通过构造函数注入，后续可以替换为 SerpAPI、Tavily、Bing 或公司内部搜索。
- `WebFetchTool`
  - `ToolRuntime` 兼容工具，名称为 `web_fetch`。
  - 拉取页面 HTML，抽取 `title` 和清洗后的正文预览。
- `CachedWebFetch`
  - 同样以 `web_fetch` 名称注册，作为 fetch 工具装饰器。
  - 在 workspace 下保存按 URL hash 命名的 JSON 缓存，避免重复抓同一页面。
- CLI 开关
  - `competitive-intel run --real-web ...`
  - `competitive-intel chat --real-web ...`
  - 不传该开关时继续使用 fake web tools，保证测试和演示稳定。

## 架构边界

真实 Web 能力仍然只属于 Collector 的工具预算。Analyst、Writer、Reviewer 不直接访问网络，它们只能消费已经落到 artifact store 的 sources/claims/reports。这样可以保持 A2A 协作系统的差异化：工具使用和证据落库发生在明确角色边界内，后续审核、返工、看板都能追踪。

## 当前取舍

- 没有引入外部依赖，降低本地运行门槛。
- HTML 解析是轻量实现，只覆盖基础搜索和页面正文预览。
- 没有做 robots、域名限流和浏览器渲染，这些留给后续可靠性模块。
- 真实 Web 是 opt-in，避免默认测试受网络环境影响。

## 测试

- `tests/unit/test_real_web_tools.py`
  - 搜索适配器限流。
  - DuckDuckGo HTML 解析。
  - 页面 title/正文抽取。
  - workspace fetch 缓存复用。
  - HTTP 异常归一化。
- `tests/unit/test_cli_entrypoint.py`
  - CLI 暴露 `--real-web` 开关。

## 完成标准

- fake 模式默认行为不变。
- 真实 Web 工具通过相同 `ToolRuntime` 合约进入 harness。
- workspace 模式可以缓存 fetch 结果。
- 网络工具失败不会绕过 harness 的错误处理。
