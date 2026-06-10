# 学习文档 23：结构化 Agent Prompt 与输出校验（已完成）

## 一句话概括

**模块 23 确保每个 agent 知道自己的职责、输入、输出、证据入口、失败路由和自检标准；LLM 输出仍必须通过结构化 validator，不能因为 prompt 写得好就信任原始文本。**

## 为什么需要它

当 agent 开始调用真实 LLM 后，最大风险不是“模型能不能写”，而是：

- Analyst 是否只看 source snippet 就产出 claim；
- Writer 是否复述同一段 source summary；
- Reviewer 是否忘记用户原始问题和竞品列表；
- Reviewer 是否只给自然语言建议，无法路由；
- rework 后 Reviewer 是否忘记上一轮自己提过什么。

所以 prompt 现在不是一句 system role，而是一份 agent contract。

## 四个角色的 Prompt Contract

| Agent | 必须看到 | 必须输出 | 自检重点 |
|---|---|---|---|
| Collector | 用户请求、竞品、问题维度、工具结果、可选 `collector_rework_plan` | JSON `sources` 或 tool calls | 是否尝试本产品、竞品、对比维度；是否优先执行 reviewer 定向补采 |
| Analyst | sources、source metadata、`content_ref`、`content_excerpt`、用户问题、prior feedback | JSON `claims` | 每条 factual claim 是否有 `source_ids`；是否基于完整证据而非隐藏知识 |
| Writer | claims、sources、`content_ref`、`content_excerpt`、report history、prior feedback | JSON `sections` | 是否回答用户问题；是否使用 claim/source id；是否避免无证据扩写 |
| Reviewer | request、competitors、coverage gaps、source metadata、claims、latest report、report history、prior feedback | JSON decision / feedback | 是否满足用户问题；竞品信息是否充分；历史 blocking feedback 是否解决 |

## Evidence Access

Source 表格里的 snippet 只是预览。Prompt context 会把 source metadata 中的
`content_ref` 解析成 `content_excerpt`，并把它喂给 Analyst、Writer、Reviewer。

Prompt 明确要求：

- Analyst 必须从 `content_excerpt` / `content_ref` 读取 source 证据；
- Writer 不能只复述 snippets；
- Reviewer 要拒绝“source summary only contains keywords”的报告；
- 所有 factual claims 都必须绑定 `source_ids`。

这一步解决了之前“完整 source 写到文件里，但 agent 可能没看”的问题。

## 输出校验

模型可能返回：

- 带 markdown 解释的 JSON；
- 缺少 `source_ids` 的 claim；
- 不可路由的 reviewer feedback；
- 缺少 `target_agent` 或 `required_action`；
- 缺少结构化 `entity` / `dimension`，导致 collector 无法定向补采。

结构化校验是硬边界：不合格的输出不会直接进入 artifact store。

| Agent | Validator 检查 |
|---|---|
| Collector | `sources` 必须是 list |
| Analyst | 每条 claim 必须有 `source_ids` |
| Writer | `sections` 必须是 dict |
| Reviewer | feedback 必须包含 `issue`、`target_agent`、`target_artifact_id`、`message`、`required_action`，issue 必须合法 |

## Reviewer 的特殊上下文

Reviewer 现在需要稳定看到：

- 用户原始问题；
- 竞品列表；
- coverage gaps；
- source metadata；
- `content_ref` / `content_excerpt`；
- report history；
- prior_review_feedback。

批准报告时，Reviewer 应判断最新报告是否真的解决历史 blocking feedback。
如果没有解决，应该继续输出 routable feedback，而不是因为文本更流畅就通过。

## Agent 接入状态

```text
--real-model
  -> Orchestrator._build_agents()
  -> Agent.run_round()
  -> PromptLibrary.build()
  -> build_*_model_context()
  -> ModelRuntime.complete()
  -> StructuredOutputValidator.validate()
  -> artifact store / fallback
```

四个 agent 全部支持 model-backed 模式。关键设计：

- 每个 agent 的 model-backed 方法返回前先走 validator；
- 校验失败或模型调用失败时 fallback 到确定性模板；
- prompt context 负责把 request、coverage、metadata、report history 和
  persisted content excerpts 喂完整。

## 面试怎么讲

> 我们不信任 LLM 的原始输出。每个 agent 都有自己的 prompt contract：职责是什么，输入看什么，输出写什么，证据在哪里，失败找谁，自检标准是什么。Analyst 和 Writer 被明确要求使用 content_ref/content_excerpt，而 Reviewer 会看到用户原问题、竞品、coverage gaps、source metadata、历史 report 和历史 feedback。最后仍然用 validator 做硬校验，保证模型输出能进入可路由的 artifact workflow。
