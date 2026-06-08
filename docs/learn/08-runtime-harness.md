# 08 Runtime Harness — 面试级学习笔记

## 一句话概括

**Runtime Harness 是每个 agent round 外面的可靠性外壳，负责预算、工具执行、熔断、journal 和 checkpoint，让 agent 本身只关注“下一步做什么”。**

---

## 1. 它解决什么问题？

如果直接写：

```python
while not done:
    agent.run_round(...)
```

这个系统很快会变成 demo：

- agent 重复搜索同一个 query 时没人发现
- Analyst 伪造 Collector 的工具调用时没人拦
- 每轮为什么继续、停止、重试没有结构化记录
- 崩溃后没有 checkpoint，也无法解释已经跑到哪
- 后续 dashboard / golden replay 没有稳定事件流可读

Harness 的目标不是替 agent 思考，而是给所有 agent 一套统一的运行护栏。

---

## 2. 核心职责

```python
class RuntimeHarness:
    def run_agent(self, context: RunContext, agent: Agent) -> AgentResult: ...
    def run_round(
        self,
        context: RunContext,
        agent: Agent,
        round_index: int,
        is_budget_final_round: bool = False,
    ) -> RoundEvent: ...
```

v0 做五件事：

1. 从 `AgentProfile.max_rounds` 读取 round budget。
2. 调用符合 `Agent` Protocol 的 agent。
3. 执行 agent 返回的 `ToolCall`，并把 `RunContext` 传给 `ToolRuntime` 做 per-run 权限校验。
4. 为每轮写一条 `RoundEvent` 到 `JournalStore`。
5. 有 checkpoint store 时保存轻量 `Checkpoint`。
6. 把上一轮 `ToolResult` 序列化进下一轮 `AgentState.memory["tool_results"]`。

---

## 3. 决策规则

Harness 每轮产出一个 `HarnessDecision`：

| 条件 | 决策 |
|---|---|
| Agent 返回 `completed=True` | `stop` |
| Reviewer 返回 `rework_required` | `rework` |
| 同一个 tool signature 到达 3 次 | `abort` |
| 工具执行失败或权限失败 | `retry` |
| 已经是最后一个 budget round | `abort` |
| 其他正常进展 | `continue` |

优先级很重要：如果 agent 已经完成，就直接 `stop`；如果 Reviewer 给出可修复反馈，就返回 `rework`，交给 Orchestrator/Rework Loop 处理；如果没完成但一直重复同一个 tool call，就 `abort`，避免预算被无意义消耗。

重复调用计数按 `run_id + agent + tool name + signature` 隔离。这样同一个 `RuntimeHarness` 实例连续跑多个 run 时，前一个 run 的失败模式不会污染后一个 run。

---

## 4. Tool 执行和 provenance

Harness 是唯一执行 tools 的地方：

```python
result = tool_runtime.execute(agent.name, signed_call, context=context)
```

这有两个好处：

- `ToolPolicy` 可以同时检查角色上限和 `AgentProfile.allowed_tools`。
- `ToolCall.requested_by` 必须匹配当前 agent，审计链不会被伪造。

Harness 会先计算 tool signature，再把 signature 写回 `ToolCall`，最后把 signed tool call 放进 `RoundEvent`。后续 circuit breaker 和 journal replay 都读同一个签名。

v0 的 `RoundEvent` 还没有 `tool_results` 字段，所以失败工具调用先用 signal 表达：

```text
tool_error:<tool_call_id>
```

等后面需要更完整的 observability，可以扩展 core model，把 `ToolResult` 也写进 `RoundEvent`。

Reviewer feedback 是例外，它已经是 workflow control 的一部分，所以会写入：

```text
AgentRoundResult.review_feedback
  -> RoundEvent.review_feedback
  -> AgentResult.review_feedback
  -> RunResult.review_feedback
```

这样 Orchestrator 可以直接判断 `approved / needs_rework / aborted`，不需要重新跑 Reviewer，也不需要解析自然语言。

---

## 5. Agent memory 怎么传

`run_agent()` 会维护一个 per-agent memory dictionary。每次调用 agent 时，Harness 会构造：

```python
AgentState(
    agent=agent.name,
    round=round_index,
    memory={...previous_memory},
)
```

工具执行结束后，Harness 把 `ToolResult.to_dict()` 列表写到：

```python
memory["tool_results"]
```

这样 Collector 这样的 agent 可以在第一轮请求 `web_search`，第二轮从 memory 里读取搜索结果，再请求 `web_fetch`，第三轮从 memory 里读取 fetch 结果并保存 `SourceArtifact`。Agent 不直接调用工具，也不需要知道 `ToolRuntime` 怎么注册工具。

---

## 6. Journal 和 Checkpoint 的分工

| 模块 | 记录什么 | 用途 |
|---|---|---|
| JournalStore | 每轮发生了什么、decision、tool calls、artifact ids | 审计、dashboard、golden replay |
| CheckpointStore | 当前 round 的轻量 state | 未来恢复、调试、定位中断点 |

v0 的 checkpoint 只保存：

```python
{"round": round_index, "signals": signals}
```

这不是完整恢复系统，但它给后续 recovery 模块留下了稳定接口。

---

## 7. 面试中怎么讲

这个模块可以这样讲：

> Agent 只负责产生下一轮动作，Harness 负责控制执行环境。它会把工具调用集中到一个地方执行，统一做权限校验、重复调用熔断、round budget、journal 和 checkpoint。这样每个 agent 不需要自己写可靠性逻辑，系统也能解释每轮为什么继续、停止、重试或中止。

关键点：

- `Agent` 是行为 contract。
- `ToolRuntime` 是工具执行 contract。
- `JournalStore` 是审计 contract。
- `RuntimeHarness` 是把这些 contract 串起来的可靠性层。

这就是它和普通多 agent demo 的区别：demo 关注“能不能串起来”，这个项目关注“串起来之后能不能控制、审计和恢复”。

---

## 8. 测试覆盖

```text
test_run_agent_stops_when_agent_completes
test_run_agent_aborts_after_round_budget_is_exhausted
test_repeated_identical_tool_calls_trip_circuit_breaker
test_repeated_tool_call_counts_are_isolated_by_run_id
test_run_round_passes_context_to_tool_runtime_permissions
test_run_round_rejects_tool_call_requested_by_another_agent
test_run_round_appends_one_journal_event_and_checkpoint
test_run_agent_passes_tool_results_to_next_round_memory
test_run_agent_returns_rework_decision_with_review_feedback
```

这些测试覆盖了 v0 harness 最关键的不变量：终止规则、预算、重复工具熔断、权限传递、provenance 校验、journal 和 checkpoint。
