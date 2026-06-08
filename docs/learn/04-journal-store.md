# 04 Journal Store — 面试级学习笔记

## 一句话概括

**Journal Store 是系统的审计事件流，append-only 地记录每个 agent round 发生了什么和为什么继续/停止/重试/中止。**

---

## 1. 为什么普通日志不够？

普通日志通常是给人看的：

```text
Collector fetched page X
Analyst created claim Y
```

问题是：

- 格式不稳定；
- 程序不好解析；
- 无法可靠 replay；
- dashboard/golden replay 很难基于它做统计；
- rework 前后的历史容易丢。

Journal Store 存的是结构化 `RoundEvent`：

```python
RoundEvent(
    id="run_001:collector:1",
    run_id="run_001",
    agent="collector",
    round=1,
    decision="continue",
    tool_calls=[...],
    output_artifact_ids=["source_001"],
    signals=["progress"],
)
```

---

## 2. Append-only 设计

Journal 只追加，不覆盖。

这很关键：

- 可以解释每个结论的产生路径；
- 可以看到 rework 前后的变化；
- 可以 debug agent 为什么重复调用同一个工具；
- 可以给 dashboard 提供完整 run timeline。

重复 event id 会抛 `DuplicateJournalEventError`，避免 retry 或 checkpoint 场景下重复写入。

---

## 3. Public Interface

```python
class JournalStore:
    def append(self, event: RoundEvent) -> None: ...
    def list_run_events(self, run_id: str) -> list[RoundEvent]: ...
    def list_agent_events(self, run_id: str, agent: AgentName) -> list[RoundEvent]: ...
```

接口非常小，因为 v0 的目标是先稳定审计 trail。

---

## 4. InMemory 和 SQLite

项目提供两个实现：

| 实现 | 用途 |
|---|---|
| `InMemoryJournalStore` | 单元测试、轻量本地运行 |
| `SQLiteJournalStore` | 本地持久化、CLI 调试、后续 dashboard |

两个实现必须共享同一 contract：

- append 顺序稳定；
- duplicate id 报错；
- 按 run 查询；
- 按 run + agent 查询；
- payload 字段完整保留。

---

## 5. 为什么 SQLite 存 JSON payload？

v0 常用查询只需要：

- run_id
- agent
- sequence

其他字段完整存在 JSON payload 里。

这样做的好处：

- schema 简单；
- `RoundEvent` 字段变化时不用立刻做 migration；
- replay 时可以完整恢复事件对象。

等后续 dashboard 查询变复杂，再考虑增加索引列。

---

## 6. Journal 和 Artifact Store 的区别

| 模块 | 记录什么 | 关注点 |
|---|---|---|
| Journal Store | 发生过什么 | 历史、审计、回放 |
| Artifact Store | 当前可消费什么 | active sources/claims/report |

例子：

- Journal 记录 Analyst 第 2 轮产出了 `claim_001`；
- Artifact Store 保存 `claim_001` 当前是否 active、rejected 或 superseded。

这两个视角缺一不可。

---

## 7. 面试追问

**Q: 为什么不只用 Artifact Store？**

A: Artifact Store 保存当前结构化状态，但它不完整表达“过程”。Journal 记录每轮 decision、tool calls、signals，是 replay 和 debugging 的基础。

**Q: 为什么要按 agent 查询？**

A: dashboard 和调试经常需要看某个 agent 的局部轨迹，比如 Collector 是否重复搜索、Analyst 是否一直没有进展。

---

## 8. 测试覆盖

```text
test_append_and_list_run_events_in_order
test_rejects_duplicate_event_ids
test_filters_events_by_agent
test_preserves_event_json_fields
test_sqlite_store_can_reopen_file_backed_journal
```
