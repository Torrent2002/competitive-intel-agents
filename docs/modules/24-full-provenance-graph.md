# 模块 24：完整 Provenance 图

## 目标

把 v0 的 `source_ids` 扩展成可导出的因果链：报告引用了哪些 claims，claims 由哪些 sources 支撑，sources 是哪个 agent round 产出的，以及该 round 执行了哪些 tool calls。

## 当前实现

- 新增 `competitive_intel_agents.provenance`
  - `ProvenanceNode`
  - `ProvenanceEdge`
  - `ProvenanceGraph`
  - `build_provenance_graph(journal, artifacts, run_id, report_id=None)`
  - `render_provenance_appendix(graph)`
- 图节点类型：
  - `report`
  - `claim`
  - `source`
  - `event`
  - `tool_call`
- 图边类型：
  - `uses_claim`
  - `supported_by`
  - `uses_source`
  - `produced_by`
  - `executed_tool`
- 缺失链路不会 crash，而是进入 `graph.missing`，导出的 appendix 会显示 `Missing provenance`。

## 架构边界

Provenance 图只从 `JournalStore` 和 `ArtifactStore` 构建，不修改运行状态。这样 CLI、Web Dashboard、Report Export、Golden Replay 都可以复用同一个因果视图，而不是各自拼一套链路逻辑。

## 当前取舍

- 不引入图数据库，图是运行时导出对象。
- 当前 source 到 tool call 的映射基于 `RoundEvent.output_artifact_ids` 和同 round 的 `tool_calls`。
- 对 v0/v1a 已存在的 artifact 不要求额外 parent 字段，避免迁移成本。

## 测试

- `tests/unit/test_provenance_graph.py`
  - report -> claim -> source -> event -> tool_call 链路完整。
  - 缺失 claim/source/event 会被显式报告。

## 完成标准

- 最终报告可以解释每个来源和结论来自哪个 agent round。
- provenance appendix 可以作为后续 report export 的证据附录。
