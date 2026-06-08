# 20 Persistent Local Workspace — 面试级学习笔记

## 一句话概括

**Persistent Local Workspace 把一次 run 的 artifacts、journal events 和 run metadata 存到本地目录，让 CLI 结果跨进程可检查。**

## 1. 为什么需要持久化？

没有 workspace 时，CLI 运行结束后，内存里的 stores 就没了。

这会导致：

- dashboard 只能在同一个进程里看；
- 不能用 run id 追溯之前的结果；
- 不能列出历史 runs；
- Web UI 和 report export 没有稳定数据来源。

模块 20 加入本地 workspace：

```text
.competitive-intel/
  artifacts.sqlite
  journal.sqlite
  runs.json
```

## 2. LocalWorkspace 提供什么？

```python
workspace = LocalWorkspace(".competitive-intel")

workspace.artifacts  # SQLiteArtifactStore
workspace.journal    # SQLiteJournalStore
workspace.save_run_result(result)
workspace.get_run_result(run_id)
workspace.list_run_results()
```

Artifacts 和 journal 用 SQLite，run metadata 用 `runs.json`。

## 3. CLI 怎么用？

```bash
competitive-intel run \
  --input tests/fixtures/request.json \
  --workspace .competitive-intel

competitive-intel runs --workspace .competitive-intel

competitive-intel dashboard \
  --run-id run_xxx \
  --workspace .competitive-intel
```

这样第二个进程也能读取第一个进程写入的数据。

## 4. 面试怎么讲

可以说：

> 模块 20 把系统从一次性内存 demo 变成可追溯的本地工作区。ArtifactStore 和 JournalStore 已经有 SQLite 实现，LocalWorkspace 只是把它们组合成统一目录，并保存 RunResult metadata。CLI、Dashboard、未来 Web UI 都可以基于同一个 workspace 读数据。

## 5. 测试覆盖

```text
test_workspace_persists_run_results
test_workspace_exposes_sqlite_stores_across_instances
test_cli_run_persists_workspace_and_show_dashboard
test_cli_dashboard_reads_persisted_run_from_workspace
test_cli_runs_lists_persisted_runs
```
