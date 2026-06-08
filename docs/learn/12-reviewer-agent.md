# 12 Reviewer Agent — 面试级学习笔记

## 一句话概括

**Reviewer Agent 是质量门禁：它不写报告、不收集资料、不调用工具，只验证报告是否能追溯到 claims 和 sources，并输出可路由的结构化返工意见。**

---

## 1. 为什么 Reviewer 是架构重点？

如果只是单 agent 生成报告，模型可以“自己说自己写得不错”。这很难审计，也很难稳定返工。

本项目的 Reviewer 不是自然语言点评器，而是 workflow gate：

```text
ReportDraft
  -> claim_ids
  -> AnalysisClaim.source_ids
  -> SourceArtifact
```

只要这条链断了，Reviewer 就返回 `ReviewFeedback`，并明确应该返给哪个 agent。

---

## 2. Reviewer 不做什么？

Reviewer v0 刻意保持边界很窄：

- 不调用 web_search / web_fetch；
- 不改写 report；
- 不创建新 artifact；
- 不做深度事实核验；
- 不靠 prompt 文本判断是否通过。

这样它的行为可测试、可复现，也方便后续 Rework Loop 消费。

---

## 3. 输入和输出

输入来自 artifact store：

```text
active ReportDraft
active AnalysisClaim list
active SourceArtifact list
```

输出走 `AgentRoundResult`：

```python
AgentRoundResult(
    completed=False,
    signals=["rework_required"],
    review_feedback=[
        ReviewFeedback(
            issue="missing_source",
            target_agent="collector",
            target_artifact_id="source_001",
            message="...",
            required_action="...",
        )
    ],
)
```

通过时：

```python
AgentRoundResult(
    completed=True,
    output_artifact_ids=[report.id],
    signals=["approved"],
)
```

---

## 4. 检查顺序

当前实现按固定顺序检查：

1. 报告是否包含必需章节：`Overview`、`Feature comparison`、`Pricing`、`SWOT`、`Sources`；
2. `ReportDraft.claim_ids` 是否都能找到 active claim；
3. `ReportDraft.source_ids` 是否都能找到 active source；
4. claim 自己引用的 `source_ids` 是否都能找到 active source；
5. report 声明的 source 是否至少被一个 referenced claim 覆盖。

固定顺序的好处是测试稳定，后续自动返工时不会因为反馈顺序漂移导致 replay 不稳定。

---

## 5. 反馈如何路由？

Reviewer 的 `issue` 和 `target_agent` 是显式映射：

```text
missing_source      -> collector
unsupported_claim   -> analyst
weak_inference      -> analyst
missing_section     -> writer
format_violation    -> writer
unclear_writing     -> writer
```

这就是 A2A 的关键：不是 agent 随便互相聊天，而是通过结构化 artifact 和 feedback 交接责任。

---

## 6. 为什么把 feedback 放进 AgentRoundResult？

如果 feedback 只放在 `message` 字符串里，后续 Rework Loop 必须解析自然语言，系统会变脆。

现在 `AgentRoundResult.review_feedback` 是结构化字段，后续可以直接做：

```text
for feedback in result.review_feedback:
    route_to(feedback.target_agent)
```

这让“审核 -> 返工 -> 再审核”成为可编排流程，而不是一段 prompt。

---

## 7. 面试可以怎么讲

可以这样解释：

> Reviewer Agent 是系统里的质量门禁。它不负责生成内容，而是验证 report、claims、sources 之间的引用链是否完整。一旦发现问题，它返回结构化 `ReviewFeedback`，包括 issue、target_agent、target_artifact_id 和 required_action。这样后续 Rework Loop 可以自动把问题路由给 Collector、Analyst 或 Writer，而不是让一个大 agent 重新猜应该怎么修。

重点强调三件事：

- Reviewer 只读 artifact store，保证职责单一；
- feedback 是机器可读的，不是自然语言评论；
- 它把多 agent 协作从“聊天式协作”变成“artifact-driven workflow”。

---

## 8. 测试覆盖

当前测试覆盖：

```text
test_reviewer_approves_fully_sourced_report
test_reviewer_rejects_missing_sections_with_writer_feedback
test_reviewer_rejects_unknown_report_claim_with_analyst_feedback
test_reviewer_routes_missing_source_to_collector
test_reviewer_rejects_report_source_ids_not_covered_by_claims
test_reviewer_can_run_through_harness_without_tools
test_agent_round_result_round_trips_review_feedback
```

这些测试保证 Reviewer 的审核结果既能给人解释，也能给后续 orchestrator/rework loop 直接消费。
