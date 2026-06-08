# 学习文档 23：结构化 Agent Prompt 与输出校验

## 这个模块解决什么

当 agent 开始调用真实 LLM 后，最大风险不是“模型能不能写”，而是“模型写出来的东西能不能进入协作系统”。模块 23 增加 prompt library 和输出 validator，确保模型输出先满足结构化契约，再进入 artifact store。

## 关键代码

- `src/competitive_intel_agents/prompts/__init__.py`
  - `AgentPromptLibrary`：按角色构建 `ModelRequest`。
  - `StructuredOutputValidator`：校验各角色结构化输出。
  - `ValidationError`：输出不符合契约时抛出。

## 四个角色的约束

- Collector
  - `sources` 必须是 list。
  - 后续可扩展为 tool plan 和 source summary 的 schema。
- Analyst
  - 每条 claim 必须有 `source_ids`。
  - 防止无来源观点进入报告链路。
- Writer
  - `sections` 必须是对象。
  - 报告引用的 `source_ids` 必须被输入 claims 覆盖。
- Reviewer
  - feedback 必须包含合法 `issue` 和 `target_agent`。
  - 必须带 `target_artifact_id/message/required_action`，保证能路由回具体 agent。

## 为什么这样设计

这个项目的核心不是“让 LLM 一次性写一篇报告”，而是让多个角色围绕 artifact、journal 和 feedback 协作。结构化校验就是这套系统的硬边界：

1. Prompt 负责让模型知道角色任务。
2. Validator 负责阻止不合格输出进入系统。
3. Artifact store 只保存已经满足契约的数据。
4. Reviewer feedback 可以机器路由，而不是一段没人处理的自然语言。

## 后续扩展

- 用 JSON Schema 或 Pydantic schema 替换手写 validator。
- 把 prompt template 外置到配置文件。
- 加 invalid-output retry。
- 按 agent profile 注入不同模型和策略。
