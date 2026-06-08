# 16 Terminal Dashboard — 面试级学习笔记

## 一句话概括

**Terminal Dashboard 是只读可观察性视图：它从 JournalStore 和 ArtifactStore 读取一个 run 的状态，生成结构化摘要，并渲染成终端可读文本。**

---

## 1. 它解决什么问题？

一个多 agent 系统如果只能看到最终报告，很难解释：

- 每个 agent 跑了几轮？
- 有没有 tool call？
- 是否 abort 或 rework？
- 当前有多少 sources / claims？
- Reviewer 给了多少 feedback？

Dashboard 的作用就是把这些运行过程信息整理成一个本地可读摘要。

---

## 2. 模块边界

Dashboard 只读，不驱动流程。

它读取：

```text
JournalStore
ArtifactStore
run_id
```

它不做：

- 不调用 agents；
- 不调用 tools；
- 不调用 orchestrator；
- 不修改 artifacts；
- 不追加 journal events。

这个边界很重要：dashboard 是 observability，不是 workflow controller。

---

## 3. 两层接口

模块 16 分成两层：

```python
build_dashboard_snapshot(journal, artifacts, run_id)
render_dashboard(snapshot)
```

`build_dashboard_snapshot()` 返回结构化数据：

```python
DashboardSnapshot(
    run_id="run_001",
    status="completed",
    agent_rounds={"collector": 2, "analyst": 1},
    tool_call_count=1,
    source_count=2,
    claim_count=1,
    report_id="report_001",
    review_feedback_count=0,
    health_signals=["approved"],
)
```

`render_dashboard()` 只负责把它转成终端文本。

这样设计的好处是：以后 CLI、Web UI 或测试都能复用 snapshot，不需要解析 terminal string。

---

## 4. 状态推导规则

Dashboard 的状态来自 journal events：

| 条件 | status |
|---|---|
| 没有 events | `empty` |
| 任意 event 是 `abort` | `aborted` |
| 任意 event 是 `rework` | `needs_rework` |
| 最后一个 event 是 `stop` | `completed` |
| 其他情况 | 最后一个 event 的 decision |

注意：这是可观察性状态，不是新的业务决策。真正的流程控制仍然在 Harness / Orchestrator / ReworkLoop。

---

## 5. 为什么读 Journal 和 ArtifactStore？

Journal 回答“发生了什么”：

```text
agent
round
decision
tool_calls
signals
review_feedback
```

ArtifactStore 回答“当前可消费状态是什么”：

```text
active sources
active claims
latest active report
```

两者合起来，dashboard 才能同时解释过程和结果。

---

## 6. 面试可以怎么讲

可以这样说：

> Terminal Dashboard 是系统的 observability view。它不依赖 agent 内部状态，而是从 JournalStore 读取 round events，从 ArtifactStore 读取当前 active artifacts。这样 dashboard 可以展示每个 agent 的 rounds、tool call 数、health signals、source/claim 数和 reviewer feedback 数。它是只读模块，所以不会污染 workflow，也方便未来替换成 Web UI。

重点强调：

- Journal 是运行过程；
- ArtifactStore 是当前结构化产物；
- Dashboard 只读；
- snapshot 和 rendering 分离；
- empty / aborted / needs_rework / completed 都有明确状态。

---

## 7. 测试覆盖

当前测试覆盖：

```text
test_dashboard_summarizes_rounds_by_agent_and_tool_calls
test_dashboard_shows_rework_state_and_feedback_count
test_dashboard_shows_abort_state
test_dashboard_handles_empty_runs
```

这些测试保证 dashboard 是从 stores 构建摘要，而不是偷看 agent 内部实现。
