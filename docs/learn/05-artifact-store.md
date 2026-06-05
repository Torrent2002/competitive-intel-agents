# 05 Artifact Store — 面试级学习笔记

## 一句话概括

**Artifact Store 是多 Agent 之间的结构化共享内存，让 agent 通过结构化数据通信，而不是互相解析对方的原始对话 transcript。**

---

## 1. 它解决什么问题？

在一个 multi-agent pipeline（Collector → Analyst → Writer → Reviewer）里，每个 agent 产出不同的数据：

- **Collector** 产出 `SourceArtifact`（搜索到的原始资料）
- **Analyst** 产出 `AnalysisClaim`（基于 source 的分析结论）
- **Writer** 产出 `ReportDraft`（最终报告）

如果每个 agent 都把结果写成自然语言塞进下一个 agent 的 prompt，会导致：
- 下游 agent 要费力解析自然语言（不可靠）
- 信息丢失（source URL、引用链断裂）
- 无法追溯"这个结论来自哪个 source"
- Rework 时无法精确定位需要修正的 artifact

**Artifact Store 让 agent 通过强类型的结构化对象通信，每个 artifact 有唯一 ID、版本链、状态标记。**

---

## 2. 核心设计

### 2.1 三要素：不可变、版本链、状态机

```
[SourceArtifact v1] ──── superseded_by ────→ [SourceArtifact v2]
      status: superseded                           status: active
```

- **不可变**：一旦 `save_*()`，artifact 对象本身不修改
- **版本链**：新版本通过 `supersedes_id` 指向前一版本，形成链表
- **状态机**：`active → superseded | rejected`，默认查询只返回 `active`

### 2.2 为什么 InMemory 就够了，不需要 SQLite？

| 维度 | Artifact Store | Journal Store |
|---|---|---|
| 生命周期 | 一次 run 内 | 需要跨 run 审计 |
| 数据结构 | 嵌套对象（dict、list） | 扁平事件流 |
| 查询模式 | `run_id` + `type` + `status` 过滤 | 顺序扫描、去重 |
| 适合存储 | InMemory dict | SQLite / 文件 |

Artifacts 是一次 run 内的共享内存，run 结束就释放。真要重建，从 Journal 的 event trail 就能恢复。

### 2.3 核心接口设计

```python
class ArtifactStore(Protocol):
    # 写入 —— 不可变，save 后对象本身不再修改
    def save_source(self, artifact: SourceArtifact) -> None: ...
    def save_claim(self, claim: AnalysisClaim) -> None: ...
    def save_report(self, report: ReportDraft) -> None: ...

    # 读取 —— 默认只返回 active，隔离 run
    def list_sources(self, run_id: str) -> list[SourceArtifact]: ...
    def list_claims(self, run_id: str, status="active") -> list[AnalysisClaim]: ...
    def get_latest_report(self, run_id: str) -> ReportDraft | None: ...

    # 状态变更 —— 不修改对象，只改 store 内部追踪的状态
    def mark_superseded(self, artifact_id: str, replacement_id: str) -> None: ...
    def mark_rejected(self, artifact_id: str, reason: str) -> None: ...
```

重点：
- `list_sources` **没有** `status` 参数 — source 被 rework 的情况少，默认只返回 active
- `list_claims` **有** `status` 参数 — claim 是 rework 的主要对象，需要按状态过滤
- `mark_superseded` 要求 `replacement_id` 已经 save 过（防御性校验）
- `get_latest_report` 按 `version` 降序取第一个 active

---

## 3. 实现细节

### 3.1 状态追踪与 artifact 对象分离

```python
class InMemoryArtifactStore:
    def __init__(self):
        self._claims: dict[str, AnalysisClaim] = {}   # 不可变的 artifact 对象
        self._statuses: dict[str, ArtifactStatus] = {}  # 可变的状态追踪

    def mark_rejected(self, artifact_id, reason):
        self._require_artifact(artifact_id)            # 防御性校验
        self._statuses[artifact_id] = "rejected"       # 只改追踪状态
        self._rejection_reasons[artifact_id] = reason  # 保留拒绝原因
```

这是关键设计：**artifact 对象冻结不变，状态在 store 层独立追踪**。这样下游 agent 拿到的 artifact 永远是创建时的快照，不会出现"拿到一半被修改"的并发问题。

### 3.2 插入顺序保留

```python
self._run_order: dict[str, list[tuple[str, str]]] = {}
# run_id -> [(artifact_id, type), ...]

def _record(self, run_id, artifact_id, artifact_type):
    if run_id not in self._run_order:
        self._run_order[run_id] = []
    self._run_order[run_id].append((artifact_id, artifact_type))
```

为什么要保留插入顺序？让 Reviewer 能按时间线审查"这个 claim 是在哪些 source 之后产出的"，排查时序问题。

### 3.3 错误类型继承 ValueError

```python
class ArtifactNotFoundError(ValueError):
    """Raised when referencing an artifact that does not exist."""
```

继承 `ValueError` 而非 `Exception`，和项目中 `DuplicateJournalEventError` 保持一致。调用方可以统一 `except ValueError` 捕获业务错误。

---

## 4. 面试常见追问

**Q: 为什么不用 SQLite 存 artifacts？**

A: Artifacts 是嵌套文档（`sections: dict`、`source_ids: list`），塞进关系表就得把核心数据放在 `payload TEXT` JSON blob 里，SQLite 退化成了文件系统。真正的查询只用到 `run_id` + `type` + `status` 三个 key，InMemory dict 足够。Artifact 的生命周期是一次 run，不需要跨 run 持久化 — 审计走 Journal。

**Q: 怎么保证多个 agent 写 artifact 不冲突？**

A: 目前是单进程 DAG 顺序执行（Collector → Analyst → Writer），不存在并发写。未来如果并行化，可以用 artifact ID 前缀 + 写入校验来隔离。

**Q: `mark_superseded` 和直接在 save 时传 `supersedes_id` 有什么区别？**

A: `supersedes_id` 是新 artifact 创建时声明的"我是谁的新版本"。`mark_superseded` 是把旧 artifact 的状态从 `active` 改为 `superseded`。两步分开是因为：创建新版本和废弃旧版本不一定是原子操作 — 新版本可能需要 Reviewer 验证通过后才废弃旧版本。

**Q: 如何保证 rejected artifacts 不被下游消费？**

A: 所有 `list_*` 方法默认 `status="active"`，rejected 的 artifact 不会出现在默认结果里。下游 agent 通过 `list_claims(run_id)` 拿到的永远是干净的 active 集合。审计时可以用 `list_claims(run_id, status="rejected")` 显式查询。

**Q: Artifact 可以从 Journal 重建吗？**

A: 可以。Journal 里每个 `RoundEvent` 包含 `output_artifact_ids`，配合 event payload 可以重建 artifact 的生命周期。这就是为什么 Artifact Store 不需要自己持久化 — Journal 已经是单一事实来源。

---

## 5. 和前后模块的关系

| 依赖方向 | 模块 | 关系 |
|---|---|---|
| ← 依赖 | 02 Core Models | `SourceArtifact`, `AnalysisClaim`, `ReportDraft`, `VersionedArtifact` |
| → 被依赖 | 09 Collector Agent | Collector 产出 `SourceArtifact` → `save_source()` |
| → 被依赖 | 10 Analyst Agent | Analyst 读 `list_sources()` + 产出 `AnalysisClaim` → `save_claim()` |
| → 被依赖 | 11 Writer Agent | Writer 读 `list_claims()` + 产出 `ReportDraft` → `save_report()` |
| → 被依赖 | 15 Rework Loop | Rework 调用 `mark_superseded()` / `mark_rejected()` |

---

## 6. 测试覆盖

```
test_save_and_list_sources           # 基本读写
test_save_and_list_claims            # 基本读写 + 默认 status 过滤
test_get_latest_report               # 无 report 返回 None，有则返回最新版本
test_artifacts_isolated_by_run_id   # 不同 run 的 artifact 隔离
test_mark_old_claims_as_superseded  # 版本链 + 默认不返回 superseded
test_exclude_rejected_from_default  # rejected 不出现在默认结果
test_mark_superseded_side_effects   # 只影响目标 artifact
test_get_latest_report_highest_version  # 多版本取最新
```
