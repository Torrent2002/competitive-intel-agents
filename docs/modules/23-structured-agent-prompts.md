# 模块 23：结构化 Agent Prompt 与输出校验（已完成）

## 目标

为 agent 提供稳定的 prompt 边界和结构化输出契约。模型输出须先校验，再进入 artifact store。四个 agent 已全部接入 model-backed 模式。

## 当前实现

- `AgentPromptLibrary`
  - 按角色生成 `ModelRequest`，每个角色有独立 system prompt（均强制 "Return ONLY valid JSON"）：
    - Collector：输出 `sources` 数组。
    - Analyst：输出 `claims` 数组，每条 claim 必须携带 `source_ids`。
    - Writer：输出 `sections` 对象。
    - Reviewer：输出 `feedback` 数组，包含 `issue`、`target_agent`、`target_artifact_id`、`message`、`required_action`。
  - 默认 `response_format="json"`、`temperature=0.0`。
- `StructuredOutputValidator`
  - Collector：`sources` 必须是 list。
  - Analyst：每条 claim 必须有 `source_ids`。
  - Writer：`sections` 必须是 dict（Reviewer 负责 source/claim 交叉覆盖校验）。
  - Reviewer：feedback 必须可路由。
- `ValidationError`：模型输出不满足契约时抛出，agent 自动 fallback 到模板。

## Agent 接入状态

| Agent | fake 模式 | model-backed 模式 |
|---|---|---|
| Collector | 模板生成查询 + 硬编码 source 提取 | 模型生成多角度查询、相关性过滤、内容摘要 |
| Analyst | 硬编码 `"{company} evidence from {source}"` | 模型读取 source 全文，输出结构化 claims（text/source_ids/confidence/reasoning） |
| Writer | 模板填充 section | 模型撰写 5 个 section（Overview/Feature/Pricing/SWOT/Sources），每段 2-4 段文字 |
| Reviewer | 规则检查（section/claim/source 完整性） | 规则检查 + 模型语义审查（弱推理、不清晰、深度不足） |

## 架构边界

Prompt library 构造请求，validator 校验结构。它们不写 artifact、不执行工具、不决定 DAG。Agent 的 model-backed 实现通过 `ModelRuntime` 调用，validator 校验失败时自动 fallback 到模板。

## 测试

- `tests/unit/test_structured_agent_prompts.py`
  - Prompt 包含角色 system prompt、任务和上下文。
  - Analyst 无 source_ids 的 claim 被拒绝。
  - Reviewer feedback 必须可路由。

## 完成标准

- [x] provider-backed agent 有稳定的 prompt/response 契约入口。
- [x] 证据链约束在 artifact 写入前可校验。
- [x] Reviewer feedback 保持 A2A 路由能力。
- [x] 四个 agent 全部支持 model-backed 模式（`--real-model` 开关）。
- [x] 模型输出解析失败时优雅 fallback，不阻塞 pipeline。
