# 学习文档 21：真实 Web 采集工具

## 这个模块解决什么

v0 的 Collector 使用 fake `web_search/web_fetch`，优点是稳定，缺点是只能展示协作流程。模块 21 补上真实信息采集入口，让系统可以根据竞品名称做可选的 Web 搜索和网页抓取。

关键点是：真实 Web 不是直接写进 agent，而是作为 `ToolRuntime` 工具注册进去。这样 Collector 仍然只声明工具调用，harness 负责执行、记录、限流和错误处理。

## 关键代码

- `src/competitive_intel_agents/runtime/web_tools.py`
  - `HttpClient`：最薄的 HTTP 边界，便于测试注入。
  - `DuckDuckGoSearch`：搜索适配器。
  - `WebSearchTool`：`ToolRuntime` 可执行的搜索工具。
  - `WebFetchTool`：抓取网页并抽取正文预览。
  - `CachedWebFetch`：workspace 下的 fetch 缓存装饰器。
- `src/competitive_intel_agents/cli/__init__.py`
  - `run/chat --real-web`：显式启用真实 Web 工具。

## 为什么这样设计

如果把网络请求直接写进 Collector，后续会很难测试，也很难解释 agent 的能力边界。现在的设计是：

1. Agent 只产出 tool call。
2. ToolRuntime 执行工具。
3. Harness 记录工具调用、错误和 round 事件。
4. Artifact store 保存最终 sources。

这体现了项目的差异化：不是“单 agent 调工具再总结”，而是有角色边界、证据落库、运行审计和 reviewer gate 的协作系统。

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

带 workspace 时，网页 fetch 结果会缓存到 `.competitive-intel/cache/web_fetch`。

## 后续扩展

- 增加 robots/rate-limit/domain budget。
- 替换 DuckDuckGo HTML 适配器为稳定搜索 API。
- 支持浏览器渲染抓取动态页面。
- 把 fetch 内容转成更完整的 `SourceArtifact` provenance。
