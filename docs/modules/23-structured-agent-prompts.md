# 模块 23：结构化 Agent Prompt 与输出校验

## 目标

为后续从 deterministic agent 迁移到 provider-backed agent 做准备：每个 agent 都有明确的 prompt 边界和结构化输出契约，模型输出必须先校验，再进入 artifact store。

## 当前实现

- `AgentPromptLibrary`
  - 按角色生成 `ModelRequest`。
  - 每个角色有独立 system prompt：
    - Collector：证据优先，只输出工具计划或来源摘要。
    - Analyst：每条事实 claim 必须携带 source ids。
    - Writer：只能基于给定 claims/source ids 写报告。
    - Reviewer：输出可路由 feedback。
  - 默认 `response_format="json"`、`temperature=0.0`。
- `StructuredOutputValidator`
  - Collector：`sources` 必须是 list。
  - Analyst：每条 claim 必须有 `source_ids`。
  - Writer：报告引用的 `source_ids` 必须被输入 claims 覆盖。
  - Reviewer：feedback 必须包含合法 `issue`、`target_agent`、`target_artifact_id`、`message`、`required_action`。
- `ValidationError`
  - 模型结构化输出不满足契约时抛出。

## 架构边界

Prompt library 只负责构造请求，validator 只负责校验结构。它们不写 artifact、不执行工具、不决定 DAG。这样后续可以把某个 agent 从 deterministic 实现替换成 LLM 实现，而不影响 harness、journal、artifact store 和 reviewer feedback 的路由模型。

## 当前取舍

- v1a 还没有把默认四个 agent 全部切到 LLM 生成，避免一次性扩大风险。
- validator 先覆盖最关键的“证据链不断裂”和“feedback 可路由”约束。
- 暂不引入 JSON Schema 依赖，后续如果结构复杂度提高，可以把 validator 替换为 schema engine。

## 测试

- `tests/unit/test_structured_agent_prompts.py`
  - Prompt request 包含角色 system prompt、任务和上下文。
  - Analyst 无 source ids 的 claim 会被拒绝。
  - Writer 不能引入 claims 未覆盖的 source ids。
  - Reviewer feedback 必须可路由。

## 完成标准

- provider-backed agent 有稳定的 prompt/response 契约入口。
- 证据链约束在 artifact 写入前可以被校验。
- Reviewer feedback 仍然保持 A2A 路由能力。
