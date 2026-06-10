# 学习文档 21：真实 Web 采集工具

## 这个模块解决什么

真实 Web 采集不只是“拿一个 snippet”。在竞品分析里，证据最重要，所以当前实现把所有信息获取统一成同一条规则：

```text
search / fetch -> clean full text -> persist full text -> return compact summary + content_ref
```

也就是说，fetch 返回给 agent 的不是完整大文本，而是：

- 本地持久化路径 `content_ref`；
- 清洗后全文的 hash 和字数；
- 可放进 prompt 的摘要和 preview；
- 后续 agent 可读取的 `content_excerpt`。

这样既保护上下文长度，又不丢失原始证据。

## 关键代码

- `src/competitive_intel_agents/runtime/web_tools.py`
  - `HttpClient`：最薄的 HTTP 边界，便于测试注入。
  - `DuckDuckGoSearch`：搜索适配器。
  - `WebSearchTool`：`ToolRuntime` 可执行的搜索工具。
  - `WebFetchTool`：抓取网页并抽取清洗后的正文；真实运行时使用
    `max_chars=None` 以保留完整正文。
  - `CachedWebFetch`：workspace 下的 fetch 缓存装饰器；读取旧缓存时也会
    补充持久化内容 metadata。
- `src/competitive_intel_agents/runtime/content_store.py`
  - `LocalContentStore`：按 hash 保存完整清洗文本。
  - `PersistedContentTool`：包装任意内容获取工具，把完整内容写入
    content store，并把 `content_ref` 等 metadata 放回 tool result。
- `src/competitive_intel_agents/agents/prompt_context.py`
  - 根据 source metadata 中的 `content_ref` 读取 `content_excerpt`，喂给
    Analyst、Writer、Reviewer。
- `src/competitive_intel_agents/cli/__init__.py`
  - `run/chat/web --real-web` 注册真实 search/fetch 工具链。

## 为什么这样设计

如果把完整网页直接塞进每轮 prompt，会爆上下文，也会让 dashboard 难读。
如果只保存摘要，Analyst 和 Writer 又会在少量关键词上反复编报告。

所以当前规则是：

1. 网络工具抓完整内容。
2. `PersistedContentTool` 把完整清洗文本保存到 workspace。
3. Tool result 返回 compact summary、preview、`content_ref`、hash、字数。
4. Collector 保存 `SourceArtifact` 和 metadata。
5. 下游 prompt context 按需读取 excerpt；必要时可以根据 `content_ref` 追到全文。

这让系统同时满足：

- prompt 可控；
- 证据不丢；
- reviewer 能检查 source 是否只是关键词摘要；
- dashboard 能展示 source metadata；
- 后续可以替换搜索/抓取供应商而不改 agent contract。

## 如何运行

默认仍使用 fake 工具：

```bash
PYTHONPATH=src python -m competitive_intel_agents.cli run \
  --input tests/fixtures/request.json
```

启用真实 Web：

```bash
PYTHONPATH=src python -m competitive_intel_agents.cli run \
  --input tests/fixtures/request.json \
  --workspace .competitive-intel \
  --real-web \
  --show-dashboard
```

带 workspace 时：

- fetch 缓存保存到 `.competitive-intel/cache/web_fetch`；
- 完整清洗文本保存到 `.competitive-intel/content`；
- source metadata 里会出现 `content_ref`、`content_hash`、`char_count`。

## 失败语义

外部搜索可能因为网络、SSL、限流失败。工具失败不会绕过 harness：

- search/fetch 错误会进入 `ToolResult.error`；
- journal 记录 `tool_error:*`；
- Collector 可在部分失败时继续使用成功来源；
- 如果最终证据不足，Reviewer/ReworkLoop 应把它表达成
  `needs_more_evidence`，而不是假装报告通过。

## 后续扩展

- 增加稳定搜索 API 或内部搜索适配器。
- 支持浏览器渲染抓取动态页面。
- 为 content store 加全文索引和 source diff。
- 增加 robots、rate limit、domain budget。
