# 17 Golden Replay — 面试级学习笔记

## 一句话概括

**Golden Replay 是回归测试层：它用固定输入跑 deterministic fake pipeline，并检查证据链、控制流和预算指标，而不是比较最终报告的具体措辞。**

---

## 1. 为什么不能只比较报告文本？

竞品分析报告是自然语言，措辞会变化。

如果 golden test 做 exact text matching，会很脆：

- prompt 微调会导致文本变化；
- 同义表达会误报失败；
- 文本好看不代表证据链正确；
- 模型可能写得很流畅但 claim 没有 source。

所以模块 17 检查的是 workflow quality：

```text
sources
claims
report source coverage
reviewer events
tool-call budget
round budget
artifact lineage
```

这比“报告长得像不像上一版”更适合这个项目。

---

## 2. Golden case 结构

当前 case 放在：

```text
tests/golden/case_01_single_competitor/
  input.json
  expected.json
```

`input.json` 是用户请求：

```json
{
  "company": "Notion",
  "market": "productivity",
  "competitors": ["Coda"],
  "questions": ["pricing", "collaboration features"]
}
```

`expected.json` 是指标约束：

```json
{
  "min_source_count": 2,
  "min_claim_count": 2,
  "min_claim_source_coverage_ratio": 1.0,
  "require_report_source_coverage": true,
  "terminal_status": "approved",
  "require_reviewer": true
}
```

以后新增 case 只需要加目录，不需要改 runner 代码。

---

## 3. Runner 和 Evaluator 分工

模块 17 分两层：

```python
GoldenReplayRunner(root).run_all()
evaluate_golden_metrics(journal, artifacts, run_result, expected)
```

Runner 负责：

- 加载 golden cases；
- 创建 deterministic `Orchestrator`；
- 跑 fake pipeline；
- 把 stores 和 run result 交给 evaluator。

Evaluator 负责：

- 从 `JournalStore` 读 round events；
- 从 `ArtifactStore` 读 active/all artifacts；
- 计算 source/claim/report/reviewer/lineage 指标；
- 返回结构化 `MetricFailure`。

这样 evaluator 可以独立测试，也能用于 CI。

---

## 4. 当前 v0 指标

核心指标包括：

- 必需 section 是否存在；
- source 数是否达标；
- claim 数是否达标；
- claim 的 source coverage ratio；
- report.source_ids 是否都存在；
- reviewer feedback 数是否超标；
- total rounds 是否超预算；
- tool calls 是否超预算；
- terminal status / decision 是否符合预期；
- 是否真的跑过 Reviewer；
- rework attempt 数是否超标；
- replacement artifact lineage 是否有效。

这些指标直接对应这个项目的差异化：证据优先、角色边界、可审计返工，而不是一段漂亮文本。

---

## 5. 失败如何表达？

失败会返回结构化对象：

```python
MetricFailure(
    metric="report_source_coverage",
    expected=True,
    actual=["source_missing"],
    message="report has missing source ids: ['source_missing']",
)
```

这让 CI 输出能明确告诉你是哪类能力退化了：

- 少 source；
- 少 claim；
- 跳过 Reviewer；
- source coverage 掉了；
- lineage 断了；
- budget 超了。

---

## 6. 面试可以怎么讲

可以这样说：

> Golden Replay 不是评估报告文笔，而是评估工作流质量。它用固定输入跑本地 fake pipeline，然后从 JournalStore 和 ArtifactStore 计算指标，比如 source count、claim source coverage、report source coverage、reviewer 是否执行、tool-call budget 和 artifact lineage。这样即使最终报告措辞变化，只要证据链和控制流没有退化，测试就不会误报；反过来，如果报告看起来完整但跳过 Reviewer 或引用了不存在的 source，Golden Replay 会失败。

重点强调：

- 不比较 exact prose；
- 不依赖外部 API；
- 失败是结构化 metric；
- 检查证据链和控制流；
- 适合 CI。

---

## 7. 测试覆盖

当前测试覆盖：

```text
test_loads_golden_cases_from_directory
test_golden_replay_runner_passes_fake_pipeline_case
test_golden_metrics_fail_when_required_section_missing
test_golden_metrics_fail_when_report_has_unsupported_source
test_golden_metrics_fail_when_claim_source_coverage_drops
test_golden_metrics_fail_when_reviewer_was_skipped
test_golden_metrics_fail_when_artifact_lineage_is_broken
```

这些测试证明模块 17 检查的是系统能力，不是报告表面文本。
