# 00 Project Positioning — 面试级学习笔记

## 一句话定位

**这个项目不是为了证明多 agent 比单 agent 更聪明，而是把竞品分析做成可审计、可返工、可回放的 evidence-first workflow。**

---

## 1. 单 agent 能不能做？

能。

一个强模型完全可以：

1. 搜索资料；
2. 总结竞品信息；
3. 分析优劣势；
4. 写最终报告。

所以面试时不能把卖点讲成“我用了四个 agent”。如果只是四个 prompt 串起来，面试官很容易问：为什么不用一个 agent？

正确回答是：

> 单 agent 可以产出报告，但它很难稳定回答“每个结论从哪来、哪个阶段错了、如何只修一个 unsupported claim、怎么做回归测试”。这个项目用多 agent 和 artifact pipeline，是为了把竞品分析变成可控制的生产流程。

---

## 2. 真正差异化是什么？

### Evidence-first

系统不是先写报告，而是先建立证据链：

```text
SourceArtifact -> AnalysisClaim -> ReportDraft -> ReviewFeedback
```

最终报告只是最后一层表达，不是事实的唯一载体。

### Role-bounded

Collector 可以用 web tools。
Analyst、Writer、Reviewer 在 v0 不能直接搜网页。

这不是技术限制，而是产品语义：证据收集、分析、写作、审核必须分开，才能追踪责任边界。

### Routable rework

Reviewer 不只是说“报告不好”，而是输出结构化反馈：

```python
ReviewFeedback(
    issue="unsupported_claim",
    target_agent="analyst",
    target_artifact_id="claim_001",
    required_action="Add source support or revise the claim.",
)
```

这样系统可以只返工 Analyst 和下游 Writer/Reviewer，而不是整个任务重跑。

### Replayable

每个 round 都写 `RoundEvent`。
Dashboard、golden replay、debugging 不用解析自然语言 transcript，而是读结构化 journal。

---

## 3. 面试里的标准回答

如果被问：

> 单 agent 不也能完成吗？

可以答：

> 可以。如果目标只是生成一份看起来不错的报告，单 agent 足够。但这个项目关注的是生产可用性：每个 claim 必须有 source ids，每个阶段产出结构化 artifact，Reviewer 的反馈能路由到具体 agent 和 artifact，rework 不覆盖旧版本，Journal 可以回放每轮决策，Golden Replay 可以检测 source coverage 和 schema regression。多 agent 在这里不是为了堆复杂度，而是为了建立职责边界和审计链。

如果被问：

> Agent runtime 已经能调 subagent，你这个系统还有什么价值？

可以答：

> Runtime 解决的是执行能力，比如调用工具、调模型、调子 agent。这个项目解决的是竞品分析这个 domain 的 workflow contract：SourceArtifact、AnalysisClaim、ReportDraft、ReviewFeedback、role permissions、reviewer-driven rework、golden replay metrics。Runtime 是发动机，这个系统是带质检、工单、审计和回归测试的生产线。

---

## 4. 后续实现必须体现的点

- Analyst 不能产出没有 source ids 的 claim。
- Writer 不能绕过 claim 直接从 raw webpage 编事实。
- Reviewer 必须输出可路由 feedback。
- Rework 必须创建 replacement artifact，不能覆盖旧 id。
- Orchestrator 必须按 artifact flow 串阶段，而不是简单让一个 agent 全包。
- Golden Replay 必须测 source coverage、review rejection、round/tool budget，而不是只看最终文字。

这些点比“用了几个 agent”更重要。
