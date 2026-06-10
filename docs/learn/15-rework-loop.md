# 15 Rework Loop — 面试级学习笔记

## 一句话概括

**Rework Loop 把 Reviewer 的结构化反馈变成有预算、有路由、有版本链的自动返工；对于缺证据问题，它还会生成定向 collector research plan，而不是让 Collector 重新跑通用流程。**

---

## 1. 为什么这是差异化模块？

单 agent 方案通常是：

```text
生成报告 -> 模型自评 -> 重新生成整份报告
```

问题是：

- 不知道根因是缺 source、claim 弱，还是 report 没写清；
- 修一个 claim 可能把整份报告改乱；
- 旧版本被覆盖，审计链断；
- Reviewer 一直不满意时容易无限循环；
- 缺少竞品证据时，下一轮仍然可能搜同一批泛化 query。

本项目的做法是：

```text
ReviewFeedback(target_agent, issue, entity, dimension, question)
  -> route to earliest responsible stage
  -> create replacement / reject stale downstream artifacts
  -> for collector gaps, build collector_rework_plan
  -> rerun target stage and downstream only
  -> preserve old artifacts and journal events
```

---

## 2. 路由规则

| feedback target | rerun sequence |
|---|---|
| collector | Collector -> Analyst -> Writer -> Reviewer |
| analyst | Analyst -> Writer -> Reviewer |
| writer | Writer -> Reviewer |
| reviewer | Reviewer |

常见映射：

```text
missing_source -> collector
unsupported_claim / weak_inference -> analyst
missing_section / unclear_writing / format_violation -> writer
```

当多个 feedback 同时存在，orchestrator 优先选择最上游的 blocking target：

```text
collector -> analyst -> writer -> reviewer
```

这样系统不会在证据不足时先去润色报告。

---

## 3. Collector 缺口怎么变成 research plan

Reviewer 反馈如果是：

```text
issue: missing_source
target_agent: collector
entity: 起点阅读
dimension: market_share
question: 比较番茄小说和起点阅读的用户规模与市场份额
required_action: Collect competitor market share evidence
```

ReworkLoop 会写入：

```python
context.metadata["collector_rework_plan"] = [
    {
        "entity": "起点阅读",
        "dimension": "market_share",
        "question": "...",
        "required_action": "..."
    }
]
```

Collector 下一轮优先执行这个 plan，并在 journal signal 中标记
`targeted_rework_plan`。这比“缺信息就重跑所有 query”更接近真实研究流程。

---

## 4. 版本链怎么做？

旧 artifact 不会被覆盖。

如果 Reviewer 指向：

```text
report_001
```

ReworkLoop 会生成：

```text
report_001_v2
version = 2
supersedes_id = "report_001"
```

然后调用：

```python
artifact_store.mark_superseded("report_001", "report_001_v2")
```

这样：

- 下游默认只读 active 的新 artifact；
- 旧 artifact 仍然保留，可审计；
- lineage 校验能防止跨 run、跨 artifact type 的错误替换。

对于 reviewer 指向的虚拟 coverage key，ReworkLoop 不会伪造 supersedes
关系，而是生成下一个合法 artifact id，并把真实修复交给目标 agent。

---

## 5. 为什么要 reject downstream artifacts？

如果 Collector 补了 source，旧 claims 和 report 可能已经过时。

所以 Collector rework 会 reject active claims 和 reports：

```text
new source -> stale claims rejected -> Analyst rerun -> Writer rerun -> Reviewer rerun
```

如果 Analyst 的 claim 被替换，旧 report 可能还引用旧 claim，所以也要
reject stale report，强制 Writer 重新生成。

---

## 6. Reviewer 为什么要看到历史

Reviewer 现在不只看最新 report，还会收到：

- 原始用户问题和 competitor list；
- coverage gaps；
- source metadata 和 content refs；
- prior_review_feedback；
- report_history。

这样 reviewer 可以判断“上一轮指出的缺口是否真的解决了”，而不是只根据最新报告是否写得通顺来批准。

---

## 7. 为什么要有 max attempts？

每个 feedback item 的 key 是：

```text
(issue, target_agent, target_artifact_id)
```

默认最多尝试 2 次。如果 collector missing_source 一直修不好，最终状态应是：

```text
needs_more_evidence
```

如果非 collector 的返工一直修不好，最终状态是：

```text
rework_failed
```

这两个状态比无限循环或假装完成更诚实。

---

## 8. 测试覆盖

当前测试覆盖：

```text
test_routes_feedback_to_target_and_downstream_stages
test_rework_supersedes_report_and_reruns_writer_then_reviewer
test_rework_stops_after_max_attempts_for_same_feedback
test_rework_rejects_stale_downstream_report_for_analyst_feedback
test_rework_builds_targeted_collector_plan_from_missing_source_feedback
test_reviewer_receives_prior_feedback_and_report_history
```

---

## 面试可以怎么讲

> Rework Loop 是 reviewer feedback 的执行层。Reviewer 不只是给建议，而是返回 issue、target_agent、target_artifact_id，以及可选的 entity/dimension/question。ReworkLoop 根据 target_agent 选择从哪个阶段重跑，保留 artifact lineage，reject stale downstream artifacts，并把 collector missing_source 反馈转换成定向 research plan。这样补证据、补 claim、补 report 是三种不同路径，而不是整条 pipeline 盲目重跑。
