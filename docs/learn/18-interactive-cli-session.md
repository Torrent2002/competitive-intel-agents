# 18 Interactive CLI Session — 面试级学习笔记

## 一句话概括

**Interactive CLI Session 让用户不用写 JSON，也能在终端里输入竞品分析需求、跑完整 agent workflow，并继续查看 dashboard、report、sources、claims 和 feedback。**

## 1. 为什么需要它？

之前的 CLI 是命令式入口：

```bash
competitive-intel run --input tests/fixtures/request.json
```

这能证明 pipeline 可以运行，但用户体验仍然像批处理脚本。模块 18 增加：

```bash
competitive-intel chat
```

用户可以在终端里依次输入：

```text
Company:
Market:
Competitors:
Questions:
```

然后继续用命令查看结果。

## 2. 支持的交互命令

当前 v1a 支持：

```text
dashboard
report
sources
claims
feedback
save <path>
new
exit
```

这些命令都只是读取 Orchestrator 跑出的 stores，不重新实现业务逻辑。

## 3. 架构边界

CLI chat 仍然是薄适配层：

```text
stdin/input()
  -> CompetitiveIntelRequest
  -> Orchestrator.run()
  -> Dashboard / ArtifactStore / report renderer
```

它不直接创建 agent DAG，不直接调用 tools，不绕过 ArtifactStore。

## 4. 面试怎么讲

可以说：

> 模块 18 把系统从“只能跑一条命令”推进到“可以在终端里交互使用”。但它没有把 CLI 写成第二个 orchestrator，而是复用 Orchestrator、Dashboard 和 ArtifactStore，所以入口体验增强了，核心架构边界没有被破坏。

## 5. 测试覆盖

```text
test_cli_chat_runs_pipeline_and_accepts_inspection_commands
```

测试通过子进程 stdin 模拟真实用户输入，覆盖 dashboard/report/sources/claims/save/exit。
