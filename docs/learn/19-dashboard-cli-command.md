# 19 Dashboard CLI Command — 面试级学习笔记

## 一句话概括

**Dashboard CLI Command 把模块 16 的 dashboard 渲染能力接成真实命令，让用户可以在终端查看某个 run 的运行状态。**

## 1. 为什么模块 16 还不够？

模块 16 已经有：

```python
build_dashboard_snapshot(...)
render_dashboard(...)
```

但用户无法直接执行。模块 19 增加两个入口：

```bash
competitive-intel run --input ... --show-dashboard
competitive-intel dashboard --run-id run_xxx --workspace .competitive-intel
```

第一个是跑完立即展示；第二个是跨进程读取已持久化 run。

## 2. 输出什么？

Dashboard 输出包括：

- run id；
- status；
- source count；
- claim count；
- tool call count；
- reviewer feedback count；
- report id；
- agent rounds；
- health signals。

## 3. 架构边界

Dashboard 命令只读：

```text
LocalWorkspace -> JournalStore + ArtifactStore -> DashboardSnapshot -> render
```

它不调用 agents，不调用 Orchestrator，不修改 artifacts。

## 4. 面试怎么讲

可以说：

> Dashboard CLI 是 observability 的产品化入口。底层 dashboard 仍然是纯函数式 snapshot/render，CLI 只是把 persisted stores 接进去。这让 dashboard 可以在 run 结束后、甚至另一个进程里查看，符合 journal + artifact store 的审计设计。

## 5. 测试覆盖

```text
test_cli_run_persists_workspace_and_show_dashboard
test_cli_dashboard_reads_persisted_run_from_workspace
test_cli_dashboard_missing_run_is_readable
```
