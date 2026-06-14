# 学习文档 31：approved_with_caveats — 软终态与 reviewer 严格性

## 一句话概括

**模块 31 引入第四种正向终态 `approved_with_caveats`：当 reviewer 三轮都没能让 writer/analyst 把局部瑕疵修干净，但 writer 已经产出一份可交付的 report 时，run 不再被判 `rework_failed`，而是带着残留 feedback 作为 caveats 继续上线。**

## 为什么需要它

### 触发本次改动的真实 run

`run_bbb05fff4821`（飞书 vs 钉钉竞品分析）：

- collector 收齐 9 篇 source、analyst 输出 12 条 claim、writer 写出完整报告
- reviewer 在 SWOT 子节里**正确**指出一句"飞书团队3000-4000人、钉钉约1800人"无来源支持，且与 source_009 矛盾
- 三轮 rework 后 writer 仍未删掉这一句 → 旧逻辑：`rework_failed` + error=`max_rework_attempts_exceeded`

整份报告 95% 是好的，被一句无源声明拖到了"失败"分类，用户体感很差。

### 旧状态机的二分太粗

```
reviewer stop                 -> approved
collector + missing_source    -> needs_more_evidence
其他持续 blocker              -> rework_failed   ← 太粗
agent abort                   -> aborted
```

`rework_failed` 把两类完全不同的情况合并：

| 情况 | 是否能交付 | 旧状态 |
|------|------------|--------|
| writer 从未写出 report | 否，没有产物 | rework_failed |
| writer 写出 report 但有局部瑕疵 | 是，瑕疵已知可披露 | rework_failed（不合理） |

### 新状态机

```
reviewer stop                                    -> approved
collector + missing_source                       -> needs_more_evidence
其他 blocker AND latest report 存在              -> approved_with_caveats   ← 新
其他 blocker AND 无 report                       -> rework_failed
agent abort                                      -> aborted
```

判定函数把"是否有 active report"作为软分流的关键：报告是产物的根，没产物 → 还是失败；有产物 → 把瑕疵透明化即可上线。

## 关键代码

```python
# src/competitive_intel_agents/orchestrator/__init__.py
@staticmethod
def _status_for_unresolved_feedback(
    feedback_items: list[ReviewFeedback],
    report_id: str | None = None,
) -> str:
    if not feedback_items:
        return "rework_failed"
    if all(
        item.target_agent == "collector"
        and item.issue == "missing_source"
        and item.blocking
        for item in feedback_items
    ):
        return "needs_more_evidence"
    if report_id is not None and not any(
        item.target_agent == "collector" and item.issue == "missing_source"
        for item in feedback_items
    ):
        return "approved_with_caveats"
    return "rework_failed"
```

`RunResult` 同步增加 `caveats: list[ReviewFeedback]` 字段，并在新状态下把残留 feedback **从 `review_feedback` 搬到 `caveats`**：下游消费者沿用旧契约（`review_feedback` 非空 = run 失败）不会被打破，新通道里看到的就是"附带说明"。

```python
# orchestrator 终态构造
status = self._status_for_unresolved_feedback(remaining_feedback, report_id=report_id)
return RunResult(
    run_id=context.run_id,
    status=status,
    report_id=report_id,
    review_feedback=([] if status == "approved_with_caveats" else remaining_feedback),
    caveats=(list(remaining_feedback) if status == "approved_with_caveats" else []),
    error=rework_result.status,
)
```

## 表现层

### CLI

```
Run id: run_xxx
Run status: approved_with_caveats
Sources: 9
Claims: 12
Report id: report_xxx_005
Caveats: 1
--- Reviewer Caveats ---
  [blocking] unsupported_claim (analyst/report_xxx_005)
    SWOT 部分声称飞书团队约3000-4000人...
    Action: 从 SWOT 部分删除该团队规模声明
```

### Web dashboard

- 新增 `.status.approved_with_caveats` 配色：浅黄底深棕字（警示但成功）
- agent flow 把终态 agent 标 `completed`（而非 `aborted`），不把整条流水线染红
- run 详情页在 report 区块下方追加 **Reviewer Caveats** section，逐条列出 message + action

## 设计取舍

### 为什么 caveats 不写进 report 主体

考虑过用 `dataclasses.replace` 给 report 派生一个加 `caveats` section 的新版本（v3）。否决理由：

1. **审计混乱**：把 reviewer 的不满意写进 writer 的产物，模糊了责任边界
2. **lineage 复杂度**：要走完整 supersedes_id 链，多一处 ID 冲突坑
3. **重复来源**：`RunResult.caveats` + `report.sections["caveats"]` 两份真相，下游必然漂移

放在 `RunResult` 里、由渲染层拼接是 single source of truth：审计追溯、CLI 打印、web 渲染、未来的导出（PDF/HTML）共用同一份数据。

### 为什么不用 severity 区分

reviewer 当前所有 feedback 默认 `severity=blocking`（见 `models.py:323`）。现在按 severity 区分（minor → caveats、blocking → rework_failed）会要求先改 reviewer 让它产出 non-blocking 的 feedback。但本次改动想解决的是"reviewer 严格 + 修复失败"的场景，那种 feedback 一定是 blocking 的——按 severity 切反而绕过了真实诉求。

未来如果 reviewer 学会输出 `severity=advisory`，可以在这条规则前加一层："advisory feedback 一律不阻断、直接放 caveats"。

### 为什么保留 `needs_more_evidence` 不收编

`missing_source` 是上游证据问题，再走 caveats 等于隐瞒"证据不够"这个事实——report 的可信度根基坏了，不能上线。区分清楚：

- caveats：报告**有内容**，但有些声明站不住
- needs_more_evidence：报告本质上**没内容可写**

## 测试

`tests/unit/test_orchestrator.py` 加了两个互斥场景：

```python
def test_orchestrator_returns_approved_with_caveats_when_report_survives():
    # reviewer 反复给 unsupported_claim 反馈、target=不存在的 artifact
    # → ReworkLoop 走 ArtifactNotFoundError 安全分支
    # → outer 用尽 max_rework_attempts → status=approved_with_caveats
    assert result.status == "approved_with_caveats"
    assert result.report_id is not None
    assert result.review_feedback == []     # 移到 caveats
    assert len(result.caveats) == 1

def test_orchestrator_keeps_rework_failed_when_no_report_was_produced():
    # writer stub 从不写 report → 残留 blocker + report_id is None
    # → 仍然 rework_failed
    assert result.status == "rework_failed"
    assert result.report_id is None
    assert result.caveats == []
```

## 面试要点

1. **状态机加状态前要看现有二分是不是太粗**：旧 `rework_failed` 把"无产物"和"产物有瑕疵"合并，明显粒度不够。
2. **软失败状态需要可观察的产物边界**：`approved_with_caveats` 必须由"latest report 是否存在"来托底，否则状态会被滥用——任何 reviewer 不满意但有 stub 报告的 run 都偷偷上线。
3. **审计 vs 可读**：reviewer 的不满意写进 RunResult（结构化、机器可读）+ 渲染层拼到 report 末尾（人类可读），比直接污染 report artifact 更干净。
4. **下游契约兼容**：把 caveats 的列表换成新字段而不是塞进 `review_feedback`，让旧消费者"`review_feedback != []` ⇒ 失败"的判断仍然成立。
5. **测试不依赖 ReworkLoop 内部**：用"指向不存在的 artifact"让 prepare_changes 走 ArtifactNotFoundError 安全分支，避开 v2 ID 冲突等无关耦合。
