# 02 Core Models

## Goal

Define the shared data contracts used by every module.

## Scope

In scope:

- Run identity.
- Agent identity.
- Agent profiles.
- Requests and run results.
- Round events.
- Tool calls.
- Tool results.
- Model requests and responses.
- Agent state and round results.
- Checkpoints.
- Harness decisions.
- Source artifacts.
- Analysis claims.
- Report drafts.
- Review feedback.

Out of scope:

- Persistence.
- Model provider integration.
- Business logic.

## Core Types

```python
AgentName = Literal["collector", "analyst", "writer", "reviewer"]
HarnessDecision = Literal["continue", "stop", "retry", "rework", "abort"]
ArtifactStatus = Literal["active", "superseded", "rejected"]
ReviewIssue = Literal[
    "missing_source",
    "unsupported_claim",
    "weak_inference",
    "unclear_writing",
    "format_violation",
    "missing_section",
]
```

Required shared models:

- `CompetitiveIntelRequest`
- `AgentProfile`
- `RunContext`
- `ToolCall`
- `ToolResult`
- `ModelRequest`
- `ModelResponse`
- `AgentState`
- `AgentRoundResult`
- `AgentResult`
- `RoundEvent`
- `Checkpoint`
- `SourceArtifact`
- `AnalysisClaim`
- `ReportDraft`
- `ReviewFeedback`
- `RunResult`

## Minimal Fields

### CompetitiveIntelRequest

- `company`: target company or product.
- `market`: optional market/category.
- `competitors`: optional competitor list.
- `questions`: optional user-provided focus areas.

### RunContext

- `run_id`
- `request`
- `agent_profiles`
- `started_at`
- `metadata`

### AgentProfile

- `agent`
- `max_rounds`
- `allowed_tools`
- `model`
- `strategy`

### ToolCall

- `id`
- `name`
- `args`
- `requested_by`
- `signature`

### ToolResult

- `tool_call_id`
- `ok`
- `data`
- `error`
- `preview`

### ModelRequest

- `agent`
- `messages`
- `response_format`
- `temperature`
- `metadata`

### ModelResponse

- `ok`
- `content`
- `parsed`
- `usage`
- `error`

### AgentState

- `agent`
- `round`
- `memory`
- `last_checkpoint_id`

### AgentRoundResult

- `completed`
- `tool_calls`
- `output_artifact_ids`
- `signals`
- `review_feedback`
- `message`
- `error`

### AgentResult

- `agent`
- `decision`
- `rounds`
- `output_artifact_ids`
- `error`

### RoundEvent

- `id`
- `run_id`
- `agent`
- `round`
- `tool_calls`
- `output_artifact_ids`
- `signals`
- `decision`
- `timestamp`

### Checkpoint

- `id`
- `run_id`
- `agent`
- `round`
- `state`
- `created_at`

### SourceArtifact

- `id`
- `run_id`
- `url`
- `title`
- `snippet`
- `retrieved_at`
- `source_type`
- `status`
- `version`
- `supersedes_id`

### AnalysisClaim

- `id`
- `run_id`
- `text`
- `source_ids`
- `confidence`
- `reasoning`
- `status`
- `version`
- `supersedes_id`

### ReportDraft

- `id`
- `run_id`
- `sections`
- `claim_ids`
- `source_ids`
- `status`
- `version`
- `supersedes_id`

### ReviewFeedback

- `issue`
- `target_agent`
- `target_artifact_id`
- `message`
- `required_action`

### RunResult

- `run_id`
- `status`
- `report_id`
- `review_feedback`
- `error`

## Contract Notes

- Every persisted object should have a stable `id`.
- Every round event should include `run_id`, `agent`, `round`, `decision`, and `timestamp`.
- Claims should carry `source_ids`.
- Review feedback should carry `issue`, `target_agent`, `target_artifact_id`, and `required_action`.
- Reviewer round output carries structured feedback in `AgentRoundResult.review_feedback`, so the rework loop can route work without parsing natural language.
- Reworked artifacts must not overwrite old artifacts in place. Create a new artifact id, increment `version`, and set `supersedes_id` to the old artifact id.
- Artifact ids are immutable once saved. A duplicate artifact id is a contract error, not an upsert.
- Artifact status must be observed consistently by downstream modules. If a store marks an artifact `superseded` or `rejected`, returned model objects must expose that current `status`.
- A replacement artifact must stay inside the same `run_id` and artifact type as the artifact it supersedes.
- `AgentProfile.allowed_tools` is the per-run effective tool allowlist. It may narrow the role's maximum tool permissions, but must not grant tools outside the role boundary.
- A `ToolCall.requested_by` value is part of provenance. Runtime execution must reject calls whose `requested_by` does not match the executing agent.
- Phase 1 provenance means factual claims carry source ids. Full causal-chain replay can be implemented later.

## Tests

- Validate required fields.
- Validate invalid decisions are rejected.
- Validate invalid review issues are rejected.
- Validate a claim can reference source ids.
- Validate artifact status and version fields.
- Validate agent profile budget and allowed tool fields.
- Validate JSON serialization and deserialization.
- Validate `AgentRoundResult` round-trips nested `ReviewFeedback`.

## Done Criteria

- Models are importable from one stable module: `competitive_intel_agents.models`.
- Tests cover valid and invalid examples.
- No storage or runtime behavior is mixed into the models.

## 中文学习笔记

### 一句话定位

Core Models 是整个多 agent 系统的共享语言，定义 agent、harness、journal、artifact、reviewer 之间交换数据的结构。

### 面试中怎么讲

这个项目最重要的不是让多个 LLM 顺序调用，而是让每一步都有结构化记录、可审计、可回放。所以我先实现 Core Models，把系统里的核心对象固定下来，比如 `RunContext`、`RoundEvent`、`ToolCall`、`SourceArtifact`、`AnalysisClaim`、`ReviewFeedback`。

有了这些模型之后，后续模块不需要互相猜对方传什么字段。Collector 产出 `SourceArtifact`，Analyst 产出带 `source_ids` 的 `AnalysisClaim`，Writer 产出 `ReportDraft`，Reviewer 产出 `ReviewFeedback`，Harness 产出 `RoundEvent`。这就是系统的 contract。

### 关键设计点

- 所有共享模型统一从 `competitive_intel_agents.models` 导入，避免后续模块分散定义类型。
- 用 dataclass 做轻量模型，不引入复杂依赖，保持早期实现简单。
- `AgentName`、`HarnessDecision`、`ArtifactStatus`、`ReviewIssue` 都有限定合法值，非法状态会尽早失败。
- `AnalysisClaim` 必须带 `source_ids`，这是 Phase 1 provenance 的基础。
- Artifact 有 `status`、`version`、`supersedes_id`，为后续 rework loop 做准备，避免坏 claim 被覆盖后丢失审计记录。
- `to_dict()` / `from_dict()` 支持 JSON round-trip，方便后续 journal、artifact store、golden replay 复用。

### 核心对象怎么串起来

一个典型流程可以这样讲：

1. 用户请求被包装成 `CompetitiveIntelRequest`。
2. Orchestrator 创建 `RunContext`，里面包含 `run_id` 和各 agent profile。
3. Collector 调用工具，工具请求是 `ToolCall`，结果是 `ToolResult`。
4. Collector 保存 `SourceArtifact`。
5. Analyst 基于 source 生成 `AnalysisClaim`，每个 claim 都有 `source_ids`。
6. Writer 把 claims 组织成 `ReportDraft`。
7. Reviewer 对报告做检查，问题用 `ReviewFeedback` 表示。
8. Harness 每轮记录 `RoundEvent`，必要时保存 `Checkpoint`。
9. 最终运行结果用 `RunResult` 返回。

### 可以被追问时怎么答

如果问为什么不用 Pydantic，可以说：当前阶段目标是最小可行 contract，dataclass 足够表达结构和校验，也避免过早引入依赖。后续如果需要更强 schema validation 或 API 序列化，可以迁移到 Pydantic，但 contract 本身不会变。

如果问为什么 artifact 不直接覆盖，可以说：多 agent 系统需要审计和回放。rework 时直接覆盖旧 artifact 会丢失“为什么改、改了什么”的证据，所以用 `status/version/supersedes_id` 保留历史。

如果问 `source_ids` 和完整 provenance 的区别，可以说：Phase 1 先要求 factual claim 绑定 source id，这是最小可落地的来源约束；Phase 3 再把 source id 展开成完整 causal chain，追到具体 agent round、tool call 和 journal event。

如果问 Core Models 为什么不能有业务逻辑，可以说：它们是跨模块 contract，应该保持纯数据和基础校验。如果混入 storage、LLM 调用或 orchestration 逻辑，会让模块之间耦合变重，也更难测试。
