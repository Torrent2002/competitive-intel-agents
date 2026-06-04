# 04 Journal Store

## Goal

Persist append-only round events so every agent decision can be replayed.

## Scope

In scope:

- Append journal events.
- List events by `run_id`.
- List events by `run_id` and `agent`.
- Prevent duplicate event ids.

Out of scope:

- Full event sourcing replay.
- Database migrations.
- Dashboard rendering.

## Public Interface

```python
class JournalStore:
    def append(self, event: RoundEvent) -> None: ...
    def list_run_events(self, run_id: str) -> list[RoundEvent]: ...
    def list_agent_events(self, run_id: str, agent: AgentName) -> list[RoundEvent]: ...
```

## Storage Recommendation

Start with an in-memory implementation and a SQLite implementation behind the same interface.

## Tests

- Append and read events in order.
- Reject duplicate ids.
- Filter by agent.
- Preserve event JSON fields.

## Done Criteria

- Harness can depend on `JournalStore` from `competitive_intel_agents.journal` without knowing the storage backend.
- A run's event trail can be printed or inspected in tests.

## 中文学习笔记

### 一句话定位

Journal Store 是系统的审计日志层，负责 append-only 地记录每个 agent round 产生的 `RoundEvent`。

### 面试中怎么讲

这个项目强调“每个 agent 决策都可回放”，所以不能只靠普通日志。普通日志通常是给人看的，格式不稳定，也不一定能被程序重放。Journal Store 存的是结构化 `RoundEvent`，每条事件都有 `id`、`run_id`、`agent`、`round`、`decision`、工具调用、产物 id、signals 和 timestamp。

04 这个模块做的是最小审计存储接口：`append()` 写入事件，`list_run_events()` 按 run 查询完整轨迹，`list_agent_events()` 按 run 和 agent 查询局部轨迹。它还拒绝重复 event id，保证 journal 是 append-only 且不会意外重复写入。

### 关键设计点

- `JournalStore` 是协议接口，Harness 后续只依赖接口，不关心底层是内存还是 SQLite。
- `InMemoryJournalStore` 用于单元测试和轻量本地运行。
- `SQLiteJournalStore` 用于本地持久化，事件 payload 以 JSON 保存，保留完整 `RoundEvent` 字段。
- 查询结果按写入顺序返回，保证 replay 时顺序稳定。
- 重复事件 id 会抛 `DuplicateJournalEventError`，避免 checkpoint/retry 场景下重复写审计记录。

### 核心对象怎么串起来

一个 agent round 完成后，Harness 会构造 `RoundEvent`，然后调用：

```python
journal.append(event)
```

如果用户想看一次运行的完整轨迹，可以调用：

```python
journal.list_run_events(run_id)
```

如果只想看 Analyst 做了什么，可以调用：

```python
journal.list_agent_events(run_id, "analyst")
```

Dashboard、golden replay、debugging、provenance 查询后续都可以基于这些事件工作。

### 可以被追问时怎么答

如果问为什么要 append-only，可以说：多 agent 系统需要审计和回放。如果历史事件能被覆盖，就很难解释某个结论是怎么来的，也无法定位 reviewer rework 前后的变化。

如果问为什么 SQLite 里 payload 存 JSON，而不是把所有字段拆列，可以说：v0 阶段重点是稳定 contract 和完整保留事件结构。常用查询只需要 `run_id` 和 `agent`，其他字段作为 JSON payload 保存更灵活。等查询需求复杂后，再考虑增加索引列。

如果问为什么要同时有内存和 SQLite，可以说：内存实现让单元测试快速、无副作用；SQLite 实现让本地运行有持久化事件轨迹。二者共享同一接口，后续 Harness 不需要知道底层差异。

如果问 Journal 和 Artifact Store 的区别，可以说：Journal 记录“发生过什么”，是审计事件流；Artifact Store 保存“当前可被 agent 消费的数据”，比如 source、claim、report。Journal 偏历史轨迹，Artifact 偏共享状态。
