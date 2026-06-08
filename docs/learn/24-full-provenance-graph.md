# 学习文档 24：完整 Provenance 图

## 一句话概括

模块 24 把“报告用了哪些 source id”升级为“报告、claim、source、agent round、tool call 之间的因果链”。

## 为什么需要它

竞品分析报告最容易变成一段漂亮但不可追溯的文字。v0 已经要求 claim 带 `source_ids`，但面试或真实使用时还会继续追问：

- 这个 source 是哪个 agent 产出的？
- 它来自哪次工具调用？
- report 的某个 claim 具体依赖哪些 source？
- 如果链路断了，系统能不能指出缺哪一环？

模块 24 用 `ProvenanceGraph` 回答这些问题。

## 关键代码

- `src/competitive_intel_agents/provenance/__init__.py`
  - `build_provenance_graph(...)`
  - `render_provenance_appendix(...)`
  - `ProvenanceNode`
  - `ProvenanceEdge`
  - `ProvenanceGraph`

## 面试怎么讲

可以说：

> 我没有把 provenance 写死在 report exporter 里，而是做成从 ArtifactStore 和 JournalStore 导出的独立图视图。这样 dashboard、golden replay、report export 都能复用同一套因果链，而且不会污染 agent 的业务逻辑。

## 后续扩展

- 把 appendix 接入 report export bundle。
- 在 Web Dashboard 中展示 graph。
- 把 tool result preview 也挂到 graph 节点上。
