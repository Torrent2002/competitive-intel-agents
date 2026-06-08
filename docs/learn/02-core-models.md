# 02 Core Models — 面试级学习笔记

## 一句话概括

**Core Models 是整个系统的共享语言，定义 agents、runtime、harness、journal、artifact store 之间交换的结构化 contract。**

---

## 1. 为什么 Core Models 很重要？

这个项目的差异化不是“多个 agent 聊天”，而是 evidence-first workflow。

要做到可审计、可返工、可回放，所有中间状态都必须结构化：

```text
CompetitiveIntelRequest
RunContext
ToolCall / ToolResult
SourceArtifact
AnalysisClaim
ReportDraft
ReviewFeedback
RoundEvent
```

如果这些都只是自然语言文本，后续 Reviewer、Rework、Golden Replay 就无法稳定工作。

---

## 2. 核心数据流

```text
User input
  -> CompetitiveIntelRequest
  -> RunContext
  -> Collector writes SourceArtifact
  -> Analyst writes AnalysisClaim(source_ids)
  -> Writer writes ReportDraft(claim_ids, source_ids)
  -> Reviewer writes ReviewFeedback
  -> Harness writes RoundEvent
```

这个链条就是项目区别于单 agent 报告生成的地方。

---

## 3. 关键模型怎么讲

### `CompetitiveIntelRequest`

用户输入的结构化形式：

- company
- market
- competitors
- questions

Collector 后续会基于这些字段生成搜索 query。

### `RunContext`

一次 run 的上下文：

- `run_id`
- request
- agent profiles
- started_at
- metadata

Harness 和 agents 都通过它拿运行配置。

### `ToolCall` / `ToolResult`

Agent 不直接执行工具，而是返回 `ToolCall`。
Harness 通过 ToolRuntime 执行后得到 `ToolResult`。

这让工具权限、审计、熔断都集中在 runtime/harness 层。

### `SourceArtifact`

Collector 写入的证据：

- url
- title
- snippet
- retrieved_at
- source_type

后续所有事实都应该能追到 source。

### `AnalysisClaim`

Analyst 写入的结构化结论。

最关键字段是：

```python
source_ids: list[str]
```

没有 source ids 的 claim 不允许存在。

### `ReportDraft`

Writer 写入的报告草稿。

它必须保留：

- sections
- claim_ids
- source_ids

这样 Reviewer 可以把报告里的内容追回 claims 和 sources。

### `ReviewFeedback`

Reviewer 输出的结构化返工工单：

```python
ReviewFeedback(
    issue="unsupported_claim",
    target_agent="analyst",
    target_artifact_id="claim_001",
    required_action="Revise or add source support.",
)
```

这让 rework loop 能自动路由，而不是解析自然语言吐槽。

### `AgentRoundResult.review_feedback`

Reviewer 不应该把审核意见只写进 `message` 字符串。

模块 12 之后，`AgentRoundResult` 可以直接携带：

```python
review_feedback: list[ReviewFeedback]
```

这样下一步 Rework Loop 可以按 `target_agent` 分发返工任务：

```text
missing_source -> collector
unsupported_claim -> analyst
missing_section -> writer
```

这个字段是“多 agent 协作系统”和“单 agent 自评报告”的关键差异之一。

### `RoundEvent`

Harness 每轮写入 journal 的事件：

- run_id
- agent
- round
- decision
- tool_calls
- output_artifact_ids
- signals
- timestamp

这是 replay 和 dashboard 的基础。

---

## 4. 不变量

这些是不能破坏的 contract：

- artifact id 保存后不可覆盖；
- rework 必须创建新 artifact id；
- replacement artifact 用 `supersedes_id` 指向旧 artifact；
- factual claim 必须有 `source_ids`；
- `ToolCall.requested_by` 是 provenance 的一部分；
- `AgentProfile.allowed_tools` 只能收窄角色上限，不能扩权；
- `RoundEvent` 是审计来源，不要靠自然语言 transcript 做 replay。

---

## 5. 面试追问

**Q: 为什么不用 Pydantic？**

A: v0 用 dataclass 是为了保持依赖为零、模型轻量、测试快。当前校验需求很简单，手写 `__post_init__` 足够。后续如果需要复杂 schema、JSON schema 导出或 API 校验，可以迁移到 Pydantic。

**Q: 为什么 claim 必须有 source ids？**

A: 因为项目是 evidence-first workflow。没有 source ids 的 claim 无法被 Reviewer 验证，也无法被 Golden Replay 做 source coverage 检查。

**Q: 为什么 artifact 要有 status/version/supersedes_id？**

A: 为了支持 rework。旧 artifact 不覆盖，新 artifact 通过版本链替代旧 artifact，审计时可以看到修改历史。

---

## 6. 测试覆盖

```text
test_competitive_intel_request_requires_company
test_agent_profile_requires_positive_round_budget
test_agent_profile_rejects_invalid_agent_name
test_round_event_rejects_invalid_harness_decision
test_review_feedback_rejects_invalid_issue
test_analysis_claim_must_reference_at_least_one_source
test_artifact_status_and_version_fields_are_validated
test_model_round_trips_through_json
test_run_context_round_trips_nested_models
test_round_event_round_trips_nested_tool_calls
test_agent_round_result_round_trips_review_feedback
```
