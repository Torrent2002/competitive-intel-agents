# 13 Orchestrator — 面试级学习笔记

## 一句话概括

**Orchestrator 是领域工作流控制器：它创建一次 run 的上下文，组装默认 DAG，通过 RuntimeHarness 依次执行 Collector、Analyst、Writer、Reviewer，并把最终结果归纳成 `RunResult`。**

---

## 1. 它和 RuntimeHarness 有什么区别？

RuntimeHarness 管“单个 agent 怎么可靠运行”：

```text
round budget
tool execution
journal
checkpoint
retry / abort / rework decision
```

Orchestrator 管“整个竞品分析流程怎么走”：

```text
Collector -> Analyst -> Writer -> Reviewer
```

这两个模块分开后，系统不会变成一个又大又难测的 `run_everything()`。

---

## 2. 默认 DAG

当前模块 13 固定执行：

```text
Collector
  -> Analyst
  -> Writer
  -> Reviewer
```

每个阶段只通过 artifact store 交接：

- Collector 写 `SourceArtifact`
- Analyst 读 sources，写 `AnalysisClaim`
- Writer 读 claims，写 `ReportDraft`
- Reviewer 读 report/claims/sources，输出 approval 或 `ReviewFeedback`

这就是项目的差异化：不是多个 agent 互相聊天，而是通过结构化 artifacts 协作。

---

## 3. Orchestrator 创建什么？

一次 run 会创建：

```python
RunContext(
    run_id=...,
    request=CompetitiveIntelRequest(...),
    agent_profiles={...},
)
```

默认 profile 来自：

```text
config/agent_profiles.yaml
```

其中 Collector 有 `web_search` / `web_fetch`，其他 agent 默认没有工具权限。工具权限仍由 `ToolRuntime` / `ToolPolicy` 执行校验，Orchestrator 只负责把 profile 放进 context。

---

## 4. RunResult 状态

模块 13 定义了三个 v0 状态：

```text
approved      Reviewer 通过
needs_rework  Reviewer 返回结构化 feedback
aborted       Harness 中止，流程无法继续
```

关键点是 `needs_rework` 不等于失败。它表示当前 run 已经有足够结构化信息，可以交给模块 15 Rework Loop 做定向返工。

---

## 5. 为什么要把 feedback 贯穿模型？

Reviewer 返回：

```python
AgentRoundResult.review_feedback
```

Harness 会把它传到：

```text
RoundEvent.review_feedback
AgentResult.review_feedback
```

Orchestrator 再放进：

```text
RunResult.review_feedback
```

这样后续流程可以直接根据 `target_agent` 路由，不需要从字符串里猜“这段话到底是在让谁返工”。

---

## 6. CLI 的边界

CLI 现在只做三件事：

1. 读取 JSON 输入；
2. 构造 `CompetitiveIntelRequest`；
3. 调用 `Orchestrator().run(request)` 并打印结果。

它不复制 DAG，不直接创建 agents，不处理 artifact flow。

这个边界很适合面试讲：CLI 是入口，Orchestrator 是业务编排，Harness 是可靠运行层，Agent 是职责单元。

---

## 7. 面试可以怎么讲

可以这样说：

> Orchestrator 是项目的 workflow controller。它不让一个 agent 拿到所有能力，而是创建统一的 RunContext，把角色预算和工具授权放进 AgentProfile，然后按 Collector、Analyst、Writer、Reviewer 的顺序通过 RuntimeHarness 执行。每个阶段通过 ArtifactStore 交接结构化产物，所以后续可以审计、回放和定向返工。

重点强调：

- Orchestrator 不做工具执行，工具执行属于 Harness/ToolRuntime；
- Orchestrator 不写业务内容，内容由各 agent 产出；
- Orchestrator 不解析自然语言 feedback，只读结构化 `AgentResult.review_feedback`；
- CLI 不复制 pipeline logic。

---

## 8. 测试覆盖

当前测试覆盖：

```text
test_orchestrator_runs_default_dag_end_to_end_with_fake_tools
test_orchestrator_creates_run_context_with_role_bounded_profiles
test_orchestrator_aborts_when_harness_aborts
test_orchestrator_returns_needs_rework_with_reviewer_feedback
test_cli_module_runs_with_fixture
```

这些测试保证模块 13 不是“能跑 demo”，而是有清晰边界、可注入依赖、可解释状态的编排层。
