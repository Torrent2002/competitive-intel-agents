# 10 Analyst Agent — 面试级学习笔记

## 一句话概括

**Analyst Agent 把 Collector 收集到的 sources 转成带 `source_ids` 的结构化分析结论，它不搜网页，也不写最终报告。**

---

## 1. 它为什么不能只是另一个搜索 agent？

这个项目的差异化是 evidence-first workflow。为了让证据链清楚，Collector 和 Analyst 必须分开：

- Collector 负责找证据，写 `SourceArtifact`。
- Analyst 负责基于证据做判断，写 `AnalysisClaim`。

如果 Analyst 也直接搜索网页，后面的 Writer 和 Reviewer 就很难判断一个 claim 到底来自哪个收集阶段，source coverage 也会失真。

---

## 2. 输入和输出

输入：

```python
SourceArtifact(
    id="source_001",
    url="https://example.com/a",
    title="ACME source",
    snippet="ACME has a strong collaboration workflow.",
)
```

输出：

```python
AnalysisClaim(
    id="claim_run_001_001",
    run_id="run_001",
    text="ACME evidence from ACME source: ...",
    source_ids=["source_001"],
    confidence="medium",
    reasoning="Derived from source source_001: ACME source",
)
```

重点是 `source_ids`。没有 source ids 的 claim 不允许存在，因为后面的 Reviewer 和 Golden Replay 都依赖它做质量判断。

---

## 3. Round Flow

v0 的 Analyst 是确定性的：

```text
No active sources
  -> completed=False
  -> signals=["missing_sources"]

Has active sources
  -> skip sources that already have active claims
  -> save AnalysisClaim for each remaining source
  -> completed=True when target_claims is reached
```

它不会返回任何 `ToolCall`，所以能保证 Analyst 不绕过 Collector 去搜新资料。

---

## 4. Claim id 和去重

Claim id 使用：

```text
claim_{run_id}_{index:03d}
```

Analyst 会检查 active claims 里已有的 `source_ids`。如果一个 source 已经有 claim，就不会重复生成。

这样可以避免 harness retry 或 rework 前的重复 round 造成 duplicate artifact id，也保持 artifact pipeline 可预测。

---

## 5. 和后续模块的关系

Writer 不应该读 raw web pages，而应该读 Analyst 产出的 claims。

Reviewer 如果发现某个 claim unsupported，可以针对具体 claim id 返回：

```python
ReviewFeedback(
    issue="unsupported_claim",
    target_agent="analyst",
    target_artifact_id="claim_run_001_001",
    required_action="Revise the claim or attach better source support.",
)
```

这就是 Analyst Agent 的价值：它把“网页资料”变成了可路由、可审核、可返工的结构化结论。

---

## 6. 测试覆盖

```text
test_analyst_waits_for_sources_without_calling_tools
test_analyst_creates_sourced_claims_from_active_sources
test_analyst_reads_only_active_sources
test_analyst_does_not_duplicate_existing_claim_for_same_source
test_analyst_can_run_through_harness_without_tools
```

这些测试对应 Analyst 的核心不变量：不搜网页、只读 active sources、claim 必须带 source ids、重复运行不重复产物、能被 harness 控制。
