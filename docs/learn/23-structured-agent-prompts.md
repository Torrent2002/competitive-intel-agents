# 学习文档 23：结构化 Agent Prompt 与输出校验（已完成）

## 一句话概括

模块 23 确保 LLM 的输出不会破坏 artifact 契约。每个 agent 有结构化 system prompt + 输出 validator。模型输出失败时自动 fallback 到模板，不阻塞 pipeline。

## 为什么需要它

当 agent 开始调用真实 LLM 后，最大风险不是"模型能不能写"，而是"模型写出来的东西能不能进入协作系统"。

模型可能返回：
- 带 markdown 解释的 JSON（不裸）
- 缺少 `source_ids` 的 claim
- 不可路由的 reviewer feedback（只有自然语言，没有 target_agent）

结构化校验就是这道硬边界：不合格的输出不会进入 artifact store。

## 四个角色的 Prompt + Validator

| Agent | System Prompt 关键句 | Validator 检查 |
|---|---|---|
| Collector | "Return ONLY valid JSON with a 'sources' array" | `sources` 必须是 list |
| Analyst | "Every factual claim must include source_ids. Return ONLY valid JSON with a 'claims' array" | 每条 claim 必须有 `source_ids` |
| Writer | "Return ONLY valid JSON with a 'sections' object" | `sections` 必须是 dict（source/claim 交叉覆盖由 Reviewer 负责） |
| Reviewer | "Return routable feedback with issue, target_agent, target_artifact_id" | feedback 必须包含 `issue`、`target_agent`、`target_artifact_id`、`message`、`required_action`，issue 必须是合法类型 |

## Agent 接入状态

```
--real-model 开关 → Orchestrator._build_agents() → 每个 Agent 注入 ModelRuntime
                                                    ↓
                              Agent.run_round() → PromptLibrary.build() → ModelRuntime.complete()
                                                    ↓                               ↓
                                              validator.validate()            JSON 三层解析
                                                    ↓                               ↓
                                              存入 ArtifactStore           fallback 到模板
```

四个 agent 全部支持 model-backed 模式。关键设计：
- 每个 agent 的 model-backed 方法返回前先走 `StructuredOutputValidator.validate()`
- 校验失败或模型调用失败 → 自动 fallback 到硬编码模板 → pipeline 不中断
- Fake 模式下的 186 个测试全部通过

## 面试怎么讲

> 我们不信任 LLM 的原始输出。每个 agent 有结构化 system prompt 要求 JSON-only，有 validator 在 artifact 写入前做契约检查。模型输出失败时不会 crash pipeline——自动 fallback 到确定性模板，保证系统可用性。这比"调一下 ChatGPT 写报告"可靠得多，因为产品化场景里你没法接受模型输出格式错误导致整个 run abort。
