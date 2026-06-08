# 11 Writer Agent — 面试级学习笔记

## 一句话概括

**Writer Agent 把 Analyst 产出的 sourced claims 组织成结构化报告，它不做新研究，也不凭空新增事实。**

---

## 1. 为什么 Writer 不能直接读网页？

如果 Writer 直接读 raw web pages，它就可以绕过 Analyst 写新事实。这样 Reviewer 很难判断：

- 这个事实是不是 Analyst 认可过的 claim？
- 这个 source id 是不是存在？
- 这个 report issue 应该返工 Writer 还是 Analyst？

所以 Writer 的输入必须是结构化 `AnalysisClaim`，而不是网页 transcript。它负责表达，不负责研究。

---

## 2. 输入和输出

输入：

```python
AnalysisClaim(
    id="claim_001",
    text="ACME pricing is positioned for enterprise teams.",
    source_ids=["source_002"],
)
```

输出：

```python
ReportDraft(
    id="report_run_001_001",
    sections={
        "Overview": "...",
        "Feature comparison": "...",
        "Pricing": "...",
        "SWOT": "...",
        "Sources": "...",
    },
    claim_ids=["claim_001"],
    source_ids=["source_002"],
)
```

`claim_ids` 和 `source_ids` 是 Reviewer 追踪报告事实来源的关键。

---

## 3. Required Sections

v0 固定五个 section：

- Overview
- Feature comparison
- Pricing
- SWOT
- Sources

这些 section 先用 deterministic template 生成，而不是上来就依赖模型。这样测试稳定，也方便先把 artifact pipeline 和 reviewer contract 跑通。

---

## 4. Facts 和 Hypotheses 分离

`SWOT` section 里会明确分出：

```text
Sourced facts:
...

Hypotheses:
- Treat these as hypotheses until Reviewer approval.
```

这个设计是为了避免 recommendation / hypothesis 被误认为已经有 source 支撑的事实。面试里可以讲：报告不是不能有推测，但推测要标出来。

---

## 5. 和 Reviewer 的关系

Reviewer 后续会检查：

- required sections 是否齐全；
- `claim_ids` 是否存在且 active；
- `source_ids` 是否来自这些 claims；
- report sections 是否引用了 unsupported facts。

如果 Writer 漏 section，Reviewer 会返回：

```python
ReviewFeedback(
    issue="missing_section",
    target_agent="writer",
    target_artifact_id="report_run_001_001",
    required_action="Add the missing section.",
)
```

这就是 Writer 产物必须结构化的原因：Reviewer 反馈可以定位到 report artifact 和具体 section。

---

## 6. 测试覆盖

```text
test_writer_waits_for_claims_without_calling_tools
test_writer_creates_structured_report_from_active_claims
test_writer_uses_only_active_claims
test_writer_does_not_duplicate_existing_report
test_writer_can_run_through_harness_without_tools
```

这些测试对应 Writer 的核心不变量：不搜资料、不新增 claim/source id、只消费 active claims、生成 required sections、可通过 harness 控制。
