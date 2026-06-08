# 09 Collector Agent — 面试级学习笔记

## 一句话概括

**Collector Agent 是 pipeline 里负责收集证据的 agent：它提出搜索/抓取工具请求，并把抓取结果保存成结构化 `SourceArtifact`。**

---

## 1. 它为什么重要？

多 agent 竞品分析里，后面的 Analyst、Writer、Reviewer 都依赖 Collector 的证据质量。

如果 Collector 只是把网页内容塞进自然语言 prompt，后面会遇到几个问题：

- Analyst 不知道每个结论对应哪个 URL
- Writer 容易绕过证据直接写结论
- Reviewer 无法定位 unsupported claim
- Rework 时没法精确要求“补充哪个 source”

所以 Collector 的产出不是一段文字，而是 `SourceArtifact`：

```python
SourceArtifact(
    id="source_run_001_001",
    run_id="run_001",
    url="https://example.com/a",
    title="Page A",
    snippet="A detailed page about ACME.",
)
```

---

## 2. 职责边界

Collector 做三件事：

1. 根据 `CompetitiveIntelRequest` 生成搜索 query。
2. 根据上一轮 `ToolResult` 请求下一步工具，或者保存 source。
3. 去重 URL，避免重复 source artifact。

Collector 不做这些事：

- 不直接执行工具。
- 不调用模型。
- 不产出 `AnalysisClaim`。
- 不写 journal。
- 不决定全局流程。

这些职责分别属于 ToolRuntime、ModelRuntime、Analyst、JournalStore 和 RuntimeHarness。

---

## 3. Round Flow

v0 的 Collector 是一个简单状态机，状态来自 `AgentState.memory["tool_results"]`：

```text
Round 1: no tool_results
  -> request web_search(query)

Round 2: has web_search results
  -> dedupe URLs
  -> request web_fetch(url) for each new URL

Round 3: has web_fetch results
  -> save SourceArtifact records
  -> completed=True if target source count reached
```

这个设计的关键是：**Collector 不依赖 ToolRuntime，ToolRuntime 不依赖 Collector**。两者只通过 `ToolCall` 和 `ToolResult` 这两个 core models 通信。

---

## 4. Query 生成

Collector 用输入里的所有高价值 hint 组成 query：

```python
parts = [
    request.company,
    request.market,
    *request.competitors,
    *request.questions,
]
query = " ".join(part for part in parts if part)
```

这样用户给的 market、competitors、questions 不会被浪费。后续可以把 query generation 换成 model-based planner，但 v0 保持 deterministic，方便测试和面试演示。

---

## 5. Deduplication

Collector 有两层去重：

- 同一批 search results 里重复 URL，只生成一个 `web_fetch`。
- 已经保存过的 source URL，不再保存第二次。

这和 ArtifactStore 的 immutable id 规则配合：rework 可以新增 source，但不能覆盖旧 source。

---

## 6. 和 Harness 的关系

Collector 通过 harness 跑起来：

```python
store = InMemoryArtifactStore()
collector = CollectorAgent(store)
harness.run_agent(context, collector)
```

Harness 负责：

- round budget
- tool execution
- tool result memory
- repeated tool circuit breaker
- journal event
- checkpoint

Collector 负责：

- 读 memory 里的 tool results
- 返回下一步 tool calls
- 保存 source artifacts

这个分工让 Collector 很容易单测，也让后续 Analyst/Writer 可以复用同样的 agent pattern。

---

## 7. 测试覆盖

```text
test_collector_first_round_requests_search_query_from_run_input
test_collector_turns_search_results_into_deduped_fetch_calls
test_collector_saves_fetch_results_as_source_artifacts
test_collector_skips_urls_already_saved
test_collector_can_run_through_harness_with_fake_tools
```

这些测试覆盖了 Collector 的关键不变量：query 输入完整、工具请求正确、URL 去重、source artifact 持久化、能通过 harness 端到端跑起来。
