# 学习文档 26：集成式 Rework Orchestration

## 一句话概括

**模块 26 把 Reviewer 的 feedback 接回正常 run：orchestrator 选择最上游 blocking feedback，调用 ReworkLoop 做 bounded repair，并把缺证据和返工失败区分成不同终态。**

## 为什么需要它

之前 ReworkLoop 能修 artifact，但它不是正常 run 的一部分。用户看到
`needs_rework` 后还要手动判断下一步。集成式编排解决这个断点：

```text
Reviewer rework decision
  -> Orchestrator selects upstream blocking feedback
  -> ReworkLoop applies bounded repair
  -> Target stage and downstream stages rerun
  -> Reviewer approves or emits next feedback
  -> Orchestrator maps unresolved feedback to terminal status
```

## 关键代码

- `src/competitive_intel_agents/orchestrator/__init__.py`
  - `Orchestrator(enable_rework=True, max_rework_attempts=2)`
  - `_select_feedback_for_rework(...)`
  - `_apply_integrated_rework(...)`
  - terminal status mapping
- `src/competitive_intel_agents/rework/__init__.py`
  - route、artifact replacement、downstream rejection、targeted collector plan。

## 当前状态语义

| Status | Meaning |
|---|---|
| `approved` | Reviewer accepted the latest report. |
| `needs_rework` | Rework is disabled/pending, or feedback exists but has not been integrated. |
| `needs_more_evidence` | Collector missing-source blockers remain after bounded rework. |
| `rework_failed` | Non-collector blockers remain after bounded rework. |
| `aborted` | Harness/tool/agent execution aborted. |

这个区分很重要：缺证据不是代码失败，应该被产品化展示为“需要更多证据”。

## Feedback Selection

当 reviewer 返回多个 feedback 时，orchestrator 按最上游原则选择：

```text
collector -> analyst -> writer -> reviewer
```

示例：

- 同时缺竞品 source 和 SWOT section：先 collector；
- source 有了但 claim 没引用：先 analyst；
- claim 有了但 report 没回答：先 writer。

## Targeted Collector Rework

如果被选中的 feedback 是 collector `missing_source`，ReworkLoop 会把它转换成：

```python
context.metadata["collector_rework_plan"]
```

Collector 下一轮根据 `entity`、`dimension`、`question` 生成定向 query。
这样 reviewer 的意见会真正影响下一轮采集，而不是只触发一次泛化重跑。

## Reviewer Context Preservation

集成式 rework 必须把这些上下文继续传给 reviewer：

- 原始 request；
- competitors；
- coverage gaps；
- source metadata；
- report_history；
- prior_review_feedback；
- model_runtime 和 journal。

否则 reviewer 会忘掉上一轮不通过的原因，导致“报告仍然很单薄但通过”。

## 面试怎么讲

> Orchestrator 不自己修报告，它只负责把 reviewer 的结构化反馈接入正常 run。它优先选择最上游 blocking feedback，把修复交给 ReworkLoop；如果是缺 source，就生成 collector_rework_plan，让 Collector 带着具体缺口补采。修完后只重跑目标阶段和下游阶段。最终状态会区分 approved、needs_more_evidence、rework_failed 和 aborted，这比一个笼统 failed 更适合产品化。
