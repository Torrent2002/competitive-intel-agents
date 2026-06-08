# 03 Agent Interface — 面试级学习笔记

## 一句话概括

**Agent Interface 定义每个 agent 的最小行为 contract，并用角色边界防止 agent 变成“什么都能干”的万能对象。**

---

## 1. 为什么需要统一 Agent 接口？

Harness 不应该关心具体 agent 是 Collector、Analyst 还是 Writer。

它只需要知道：

```python
class Agent(Protocol):
    name: AgentName

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        ...
```

这样任何 agent 只要实现这个 contract，就能被 RuntimeHarness 执行。

---

## 2. 为什么用 Protocol？

`Protocol` 是结构化类型：

> 只要对象有 `name` 和 `run_round()`，它就是 Agent。

好处：

- fake agent 测试很容易；
- 真实 agent 不一定非要继承某个复杂基类；
- Harness 和 agent 实现解耦。

项目里也保留了 `BaseAgent`，作为方便的默认基类。未实现 `run_round()` 会抛 `NotImplementedError`。

---

## 3. AgentRoundResult 是什么？

Agent 每轮不直接控制系统，而是返回结果：

```python
AgentRoundResult(
    completed=False,
    tool_calls=[...],
    output_artifact_ids=[...],
    signals=["progress"],
)
```

Harness 再根据这个结果决定：

- continue
- stop
- retry
- rework
- abort

这让 agent 的“意图”和系统的“控制决策”分开。

---

## 4. 角色边界

| Agent | 能读 | 能写 | 能用工具 |
|---|---|---|---|
| Collector | run request, prior sources | SourceArtifact | web_search, web_fetch |
| Analyst | active sources, reviewer feedback | AnalysisClaim | none |
| Writer | active claims, source metadata | ReportDraft | none |
| Reviewer | report, claims, sources | ReviewFeedback | none |

这不是技术限制，而是产品语义：

- Collector 负责收集证据；
- Analyst 基于证据分析；
- Writer 基于 claims 写报告；
- Reviewer 做质量门。

如果 Writer 也能直接 web_fetch，它就可能绕过 Analyst 生成事实，证据链会断。

---

## 5. 角色上限 vs 运行授权

`AGENT_ACCESS_MATRIX` 是角色能力上限。
`AgentProfile.allowed_tools` 是本次 run 的实际授权。

最终权限是二者交集。

例子：

```text
Collector role ceiling: web_search, web_fetch
Run profile: web_fetch
Effective tools: web_fetch
```

即 profile 可以收窄权限，但不能给 Analyst 授权 web_search。

---

## 6. 和 Harness / ToolRuntime 的关系

- Agent 返回 `ToolCall`；
- Harness 把 `ToolCall` 交给 `ToolRuntime`；
- ToolRuntime 用 `ToolPolicy` 校验权限；
- Harness 写 `RoundEvent`；
- Agent 不直接写 journal。

这保证了权限和审计集中，不散落在每个 agent 里。

---

## 7. 面试追问

**Q: 为什么不让 agent 自己决定调用谁？**

A: 因为这个项目不是 chat-style A2A，而是 artifact-mediated workflow。agent 之间通过结构化 artifacts 协作，Orchestrator 控制 DAG，Harness 负责执行和审计。

**Q: 权限矩阵是不是过度设计？**

A: 不是复杂权限系统，只是轻量边界声明。它能防止后续模块无意中把 Writer/Analyst 做成能直接搜索网页的万能 agent。

---

## 8. 测试覆盖

```text
test_fake_agent_can_complete_a_round
test_fake_agent_can_request_tool_calls
test_agent_access_boundaries_are_narrow
test_tool_permissions_are_enforced_by_agent_name
test_base_agent_requires_run_round_implementation
```
