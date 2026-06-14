# 学习文档 35：Reviewer 事实校验 — claim ↔ source 交叉核查

## 一句话概括

**Reviewer 现在用 LLM 把每条 claim 的文本和它引用的 source 全文对照，标记 supported / partial / unsupported。`unsupported` claim 出 non-blocking advisory 反馈，复用 [[31-approved-with-caveats]] 软终态把瑕疵透明上报，而不是把整份报告打回 rework。**

## 为什么需要它

### 触发改动的真实场景

`run_bbb05fff4821`（飞书 vs 钉钉）的 SWOT 部分写："飞书团队 3000-4000 人、钉钉约 1800 人"。这条声明：

- ✅ source_009 提到飞书团队规模
- ❌ source_009 实际数字是 ~1800（已过时数据），跟报告里 3000-4000 矛盾
- ❌ reviewer 的旧规则只校验"claim 引用的 source_id 存在"，**不读 source 文本**

旧 reviewer 给这条 claim 全绿灯，整份报告蒙混过关。

LLM 写文章本就有"听起来对但实际错"的倾向。竞品分析尤其敏感 —— 一份"看起来专业"的报告里掺一条假数据，决策成本极高。

### 为什么不用结构化检查就够

之前 reviewer 已有的 7 个规则检查：

1. unresolved prior feedback
2. missing sections
3. unknown claim ids
4. missing source ids（id 引用是否存在）
5. uncovered source ids（source 是否被 claim 用到）
6. competitive coverage（每个竞品要有 source + claim）
7. question coverage（关键词匹配）

全是 **id-level 结构检查**，没有一条看 source 的 **content**。`source_009` 存在 ✅，`source_009` 被 `claim_swot_001` 引用 ✅ —— 完事。但 source_009 里的"1800"和 claim_swot_001 的"3000-4000"对不对得上，没人管。

需要往 reviewer 注入"读两个文本判一致性"这一步，且只能由 LLM 做（确定性规则做不了语义判定）。

### 为什么是 advisory 而不是 blocking

最早的设计是 unsupported → blocking → 触发 rework，writer 拿着这条 feedback 改报告，改不出就 `rework_failed`。否决理由：

1. **LLM 判 unsupported 有假阳性**：source 用了不同表述、claim 抽象一些层级，LLM 可能误判 "partial" 或 "unsupported"。这种边界 case 做硬阻断，会把好报告打成失败。
2. **rework 不一定能修**：3000-4000 人这条 claim，writer 没有新 source 就只能删除—但删完报告 SWOT 缺一段会触发 missing_section，循环触发新问题。
3. **用户应该看到 reviewer 的判定**：把不准确的 claim 静默 rework 掉，用户不知道 reviewer 怀疑过什么；反过来标个 ⚠ 在交付物上，用户知情决策。

所以走 [[31-approved-with-caveats]] 已经铺好的路：**advisory feedback → caveats → 报告照常交付，旁边附带说明**。

## 关键代码

### 1. `AnalysisClaim` 加 accuracy 字段

```python
# src/competitive_intel_agents/models.py

VALID_CLAIM_ACCURACY = {
    "unverified",   # 默认值，没跑 cross-check 时
    "supported",    # source 文本直接支持 claim
    "partial",      # 部分支持但有保留
    "unsupported",  # source 内容反驳或没提
}

@dataclass(frozen=True)
class AnalysisClaim(VersionedArtifact):
    text: str = ""
    source_ids: list[str] = field(default_factory=list)
    confidence: str = "medium"
    reasoning: str = ""
    accuracy: str = "unverified"   # 新增
```

`unverified` 是默认 — analyst 输出的 claim 一开始都是"还没校验"。reviewer 跑完才把它升级。这个区分很重要：unverified ≠ unsupported（一个是没看，一个是看了反对）。

### 2. Reviewer 单次批量调用 model

```python
# src/competitive_intel_agents/agents/reviewer.py

def _verify_claim_support(self, claims, sources, context):
    if self._model_runtime is None or not claims:
        return []
    
    # 收集每条 claim + 它引用的 source 全文
    verifiable = []
    payload = []
    for claim in claims.values():
        excerpts = []
        for sid in claim.source_ids:
            source = sources.get(sid)
            if source is None: continue
            excerpt = _content_excerpt(source.metadata.get("content_ref"), max_chars=4000)
            if excerpt:
                excerpts.append({"source_id": sid, "url": ..., "excerpt": excerpt})
        if not excerpts: continue   # 没全文就跳过
        verifiable.append(claim)
        payload.append({"claim_id": claim.id, "text": claim.text, "sources": excerpts})
    
    if not verifiable: return []
    
    # 单次调用判所有 claim
    task = "Cross-check each claim against the provided source excerpts. ..."
    resp = self._model_runtime.complete(prompt_lib.build(self.name, task, {...}))
    
    feedback = []
    for verdict in resp.parsed.get("verdicts", []):
        accuracy = verdict["accuracy"]
        claim = claims[verdict["claim_id"]]
        if accuracy in {"partial", "unsupported"} and accuracy != claim.accuracy:
            self._save_verified_claim(claim, accuracy, verdict["evidence"])
        if accuracy == "unsupported":
            feedback.append(self._unsupported_claim_advisory(claim, ...))
    return feedback
```

### 3. 只对 unsupported / partial 升级 lineage

```python
def _save_verified_claim(self, claim, accuracy, evidence):
    new_id = f"{claim.id}_v{claim.version + 1}_verified"
    replacement = replace(claim,
        id=new_id, version=claim.version + 1, supersedes_id=claim.id,
        accuracy=accuracy,
        reasoning=f"{claim.reasoning}\nVerification ({accuracy}): {evidence}".strip(),
    )
    try:
        self._artifacts.save_claim(replacement)
    except DuplicateArtifactError:
        return   # 上一轮 reviewer 已经处理过，跳过
```

### 4. Orchestrator 把 advisory 提升为 caveats

```python
# src/competitive_intel_agents/orchestrator/__init__.py

def _approved_or_caveats_from_reviewer(self, context):
    """如果 reviewer stop 时带 advisory feedback，走 approved_with_caveats。"""
    advisories = [fb for fb in latest_reviewer_event.review_feedback if not fb.blocking]
    if advisories:
        return RunResult(status="approved_with_caveats", caveats=advisories, ...)
    return RunResult(status="approved", ...)
```

跟 reviewer 完成的两条 path（直接 `decision=stop`、rework loop 内 reviewer stop）都接到这个 helper。

## 设计取舍

### 为什么单次 batched 调用而不是每条 claim 一次

每条 claim 一个 model 调用：

- 调用次数 = N（典型 10-15）
- N 次网络往返（即便有 retry [[32-model-retry]]，每次的 backoff 累加）
- 一次 review 总耗时可能 30-60s 起，跟 [[33-global-timeout]] 的 10 分钟全局预算挤占严重

单次批量：

- 1 次调用，prompt 里 list 所有 claim 和对应 source 全文
- prompt 大但 LLM 都能吞，typical claude-opus 上下文 200k token 远超
- LLM 一次能看到所有 claim 互相对照，判定更一致（避免某条 claim 单看像 unsupported 但放在全局看其实是合理简化）

代价：单次失败影响所有 claim 的判定，全部回退 unverified。但 [[32-model-retry]] 的 3 次重试给了瞬时错误恢复空间。

### 为什么 supported 不写回 v2

最朴素做法：每条 claim 都 lineage 升级到 v2，accuracy 字段刷新。

否决理由：

1. **artifact 噪音**：典型一次 run 12 条 claim，每次 reviewer 跑都升一次 v2 = 24 条 artifact。下游审计、provenance graph、UI 列表全要处理一堆"实际没变"的版本
2. **lineage 混淆**：v1 → v2 → v3 在 supersedes_id 链上看起来"被 reviewer 改了"，但内容没变只是 accuracy 字段
3. **rework 路径冲突**：ReworkLoop 用 `_v{n}` 命名做版本升级，reviewer 也用相同 `_v{n}` 名字会撞 ID

所以策略是：**默认状态（unverified → supported）** 保持原 claim 不动；只有**真有问题（partial / unsupported）**才升级 lineage 写回。supported 通过"没有 advisory feedback"间接表达。

副作用是再跑一轮 reviewer 又会重新判定一次（结果会一样）。这是接受的，因为 [[31-approved-with-caveats]] 的 max_rework_attempts 兜底，不会无限循环。

### 为什么没 content_ref 时 silently skip

两种处理方式：

| 方案 | 行为 |
|------|------|
| **当前**：跳过这条 claim，accuracy 维持 unverified | 没误伤 |
| **强行做**：用 source.title + source.snippet（300 字）判 | 高假阳性 |

source 没全文（content_ref 缺失）= 之前 `web_fetch` 没成功保存内容。snippet 只有 ~300 字的搜索摘要，让 LLM 据此判 "claim 是否被 source 支持" = LLM 在 source 信息严重不全时硬判 = 大概率 hallucination。

宁可不判（返回 unverified），不假装判了（返回 unsupported 误伤）。这跟 #10 的"宁可 ok=False 也不让 fake fallback 假装有答案"是同一思路。

### 为什么 reviewer stop 时也带 review_feedback（advisory）

之前 reviewer 完成时 `review_feedback=[]`，因为契约是"feedback 非空 = 有问题需要 rework"。现在改成：

```python
return AgentRoundResult(
    completed=True,
    signals=["approved"],
    review_feedback=all_feedback,   # 含 advisory，但都 blocking=False
)
```

orchestrator 判定逻辑变成：
- `decision == stop` + 全是 advisory → `approved_with_caveats`
- `decision == stop` + 没 advisory → `approved`
- `decision == rework` + 含 blocking → 走 rework loop

harness 的 `_decide` 看 `signals` 而不是 `review_feedback`，所以这层契约改动不会让 harness 错误把 stop 判成 rework（[[33-global-timeout]] 之前也是这么用 advisory caveats 的）。

### 为什么 orchestrator 要加 helper `_approved_or_caveats_from_reviewer`

reviewer 可能从两条路径完成：

1. 直接 `decision=stop`（无 rework，最普通路径）
2. rework loop 内某次 reviewer 终于满意 → `final_decision=stop`

两处都得检查 advisory。抽 helper 比两边各写一遍干净，且未来如果加新的 reviewer 终止路径（比如 [[33]] 的 timeout 把 reviewer 终止），加一行调用就行。

## 测试

`tests/unit/test_reviewer_agent.py` 加 4 个：

1. `test_reviewer_cross_check_marks_unsupported_claim_advisory` — model 返回 `unsupported`，断言：(a) `result.completed=True`（不阻断），(b) advisory feedback 含 `issue=unsupported_claim, blocking=False`，(c) claim 在 store 里有了 v2_verified，accuracy=unsupported
2. `test_reviewer_cross_check_does_not_bump_supported_claim` — model 全返回 `supported`，断言 claim 的 version 还是 1（无版本噪音）
3. `test_reviewer_skips_cross_check_without_model_runtime` — 不传 model_runtime，断言 accuracy 维持 unverified
4. `test_reviewer_skips_cross_check_when_source_content_missing` — source 没 content_ref，断言不调 model（`runtime.requests <= 1`，唯一一次是主 review，verify 完全没跑）

`tests/unit/test_orchestrator.py` 加 1 个：

5. `test_orchestrator_promotes_advisory_feedback_to_caveats` — stub harness 让 reviewer stop 同时带 advisory，断言 `status=approved_with_caveats, caveats=[advisory], review_feedback=[]`

## 面试要点

1. **结构校验 vs 内容校验是两个层次**：id 引用存在、claim 被 source 引用 — 都是结构；source 内容是否真的支持 claim — 是内容。LLM 时代必须做到内容层。
2. **advisory ≠ blocking**：硬阻断会把"看起来不太对但其实没大事"的 claim 打死，加上 LLM 假阳性放大成本。advisory + caveats 让用户知情但不停 ship。
3. **批量调用降低延迟成本**：N 次调用 vs 1 次 batched，对 [[33]] 全局超时和 [[32]] 重试预算都是关键差别。LLM 上下文足够长时优先 batch。
4. **lineage 不是越多越好**：默认状态不升 version。"supported" 等价于"无变化"，让审计图保持简洁。
5. **缺数据要 silent skip**：source 没全文就别强行用 snippet 判 — 数据不全的情况下，"不判"比"瞎判"更负责。
6. **跟 [[31-approved-with-caveats]] 串联**：本模块不需要新建状态机，只是给已存在的软终态贡献新一类 advisory（cross-check verdict）。**好的状态枚举一加倍受益于后续模块**。
7. **跟 [[32-model-retry]] / [[33-global-timeout]] 的协同**：cross-check 单次调用就用上模型重试；advisory 写法跟 [[33]] 的 timeout caveat 一致；这三个 P0 是真正的"系统稳健性套件"。
