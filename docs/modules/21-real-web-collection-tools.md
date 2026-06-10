# 模块 21：真实 Web 采集工具

## 目标

为 Collector 提供可选真实 Web 信息采集能力，并统一所有信息获取工具的证据规则：

```text
获取内容 -> 清洗全文 -> 持久化全文 -> 返回摘要 + content_ref
```

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
  - 拉取页面 HTML，抽取 `title` 和清洗后的正文。
  - 真实运行时使用 `max_chars=None` 保留完整清洗文本。
- `LocalContentStore`
  - 在 workspace 下按 hash 保存完整清洗文本。
- `PersistedContentTool`
  - 包装 fetch 类工具，把完整内容落盘，并给 tool result 添加
    `content_ref`、`content_hash`、`char_count`、`summary`、`preview`。
- `CachedWebFetch`
  - 以 `web_fetch` 名称注册，作为 fetch 工具装饰器。
  - 在 workspace 下保存按 URL hash 命名的 JSON 缓存。
  - 读取旧缓存时也会通过 content store 补齐持久化 metadata。

## 架构边界

真实 Web 能力仍然只属于 Collector 的工具预算。Analyst、Writer、Reviewer
不直接访问网络，它们只能消费已经落到 artifact store 和 content store 的
sources/claims/reports。

这保持了清晰证据路径：

```text
Collector uses tools -> SourceArtifact + content_ref -> Analyst claims -> Writer report -> Reviewer gate
```

## Source Metadata Contract

Tool result 和 `SourceArtifact.metadata` 应尽量包含：

- `content_ref`
- `content_hash`
- `char_count`
- `summary`
- `preview`
- `content_field`

下游 prompt context 会把 `content_ref` 解析为 `content_excerpt`，让模型能看
到比表格 snippet 更完整的证据。

## 当前取舍

- 没有引入外部依赖，降低本地运行门槛。
- HTML 解析是轻量实现，只覆盖基础搜索和页面正文清洗。
- 没有做 robots、域名限流和浏览器渲染。
- 真实 Web 是 opt-in，避免默认测试受网络环境影响。
- 完整文本落盘而不是直接塞进 prompt，以保护上下文长度。

## 测试

- 搜索适配器限流。
- DuckDuckGo HTML 解析。
- 页面 title/正文抽取。
- workspace fetch 缓存复用。
- content store metadata 注入。
- legacy cache 读取时补齐 persisted content。
- HTTP 异常归一化。
- CLI 暴露 `--real-web` 开关。

## 完成标准

- fake 模式默认行为不变。
- 真实 Web 工具通过相同 `ToolRuntime` 合约进入 harness。
- workspace 模式可以缓存 fetch 结果并持久化完整内容。
- 下游 agents 能通过 `content_ref` / `content_excerpt` 使用证据。
- 网络工具失败不会绕过 harness 的错误处理。
