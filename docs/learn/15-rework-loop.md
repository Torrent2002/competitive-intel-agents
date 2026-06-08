# 15 Rework Loop — 面试级学习笔记

## 一句话概括

**Rework Loop 把 Reviewer 的结构化反馈变成有预算、有路由、有版本链的自动返工，而不是让整个 pipeline 从头重跑或陷入无限循环。**

---

## 1. 为什么这是差异化模块？

单 agent 方案通常是：

```text
生成报告 -> 模型自评 -> 重新生成整份报告
```

这有几个问题：

- 无法精准定位是哪一步错了；
- 修一个 claim 可能把整份报告都改乱；
- 旧版本被覆盖，审计链断；
- 如果 Reviewer 一直不满意，容易无限循环。

本项目的做法是：

```text
ReviewFeedback.target_agent
  -> route to affected stage
  -> replace affected artifact
  -> rerun downstream only
  -> preserve old artifacts for audit
```

这就是 artifact-driven workflow 的价值。

---

## 2. 路由规则

模块 15 的 v0 路由很明确：

| feedback target | rerun sequence |
|---|---|
| collector | Collector -> Analyst -> Writer -> Reviewer |
| analyst | Analyst -> Writer -> Reviewer |
| writer | Writer -> Reviewer |

例子：

```text
missing_source -> collector
unsupported_claim -> analyst
missing_section -> writer
```

注意：路由不解析自然语言 `message`，而是信任 `ReviewFeedback.target_agent`。

---

## 3. 版本链怎么做？

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

- 下游默认只读 active 的 `report_001_v2`；
- `report_001` 仍然保留，可审计；
- lineage 校验能防止跨 run、跨 artifact type 的错误替换。

---

## 4. 为什么要 reject downstream artifacts？

如果 Analyst 的 claim 被替换了，旧 report 可能还引用旧 claim。

所以模块 15 会把 stale report 标记为 `rejected`，强制 Writer 重新生成报告：

```text
claim_001 -> claim_001_v2
report_001 -> rejected
Writer -> creates report_run_001_002
Reviewer -> reviews latest report
```

Collector rework 更上游，所以会 reject stale claims 和 reports。

Writer rework 只需要替换 report，然后 rerun Writer/Reviewer；Writer 看到已有 active replacement report 时可以 no-op，Reviewer 会审最新 report。

---

## 5. 为什么要有 max attempts？

每个 feedback item 的 key 是：

```text
(issue, target_agent, target_artifact_id)
```

默认最多尝试 2 次。

如果同一个 feedback 一直修不好，返回：

```text
max_attempts_exceeded
```

这比无限循环更工程化：后续可以把它交给人工处理、dashboard 展示或更高级的 planner。

---

## 6. ArtifactStore 为模块 15 做了什么增强？

Rework 需要读旧 artifact，即使它不是 active。

所以 ArtifactStore 现在支持：

```python
get_artifact(artifact_id)
list_sources(run_id, status=None)
list_claims(run_id, status=None)
list_reports(run_id, status=None)
```

默认读取仍然只返回 active，保护下游 agents；`status=None` 是审计、版本链和单调 id 生成用的。

---

## 7. 面试可以怎么讲

可以这样说：

> Rework Loop 是 Reviewer feedback 的执行层。Reviewer 不只是给一句自然语言建议，而是返回 issue、target_agent 和 target_artifact_id。Rework Loop 根据 target_agent 决定从哪个阶段重跑，先创建合法 replacement artifact，用 version 和 supersedes_id 保留 lineage，再 reject stale downstream artifacts，最后通过 RuntimeHarness 重跑受影响阶段和下游阶段。整个过程有 max_attempts，避免无限返工。

重点强调：

- 不是从头重跑；
- 不是覆盖旧 artifact；
- 不是解析自然语言；
- 有 attempt budget；
- 所有改动都可审计。

---

## 8. 测试覆盖

当前测试覆盖：

```text
test_routes_feedback_to_target_and_downstream_stages
test_rework_supersedes_report_and_reruns_writer_then_reviewer
test_rework_stops_after_max_attempts_for_same_feedback
test_rework_rejects_stale_downstream_report_for_analyst_feedback
test_get_artifact_returns_current_status_for_audit
test_list_artifacts_can_include_all_statuses
```

这些测试保证模块 15 的核心不是“模型觉得修好了”，而是可路由、可验证、可审计。
