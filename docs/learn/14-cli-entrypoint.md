# 14 CLI Entrypoint — 面试级学习笔记

## 一句话概括

**CLI Entrypoint 是本地可运行入口：开发者用一条命令读取请求 JSON，跑完整 fake pipeline，并看到 run summary 或生成 Markdown 报告。**

---

## 1. 为什么 CLI 也重要？

这个项目不能只停留在单元测试里。模块 14 的目标是让别人可以直接运行：

```bash
competitive-intel run --input tests/fixtures/request.json
```

或者在源码环境里：

```bash
python -m competitive_intel_agents.cli run --input tests/fixtures/request.json
```

这证明项目不是 demo 代码片段，而是有真实入口的可运行系统。

---

## 2. CLI 的边界

CLI 只做适配，不做编排。

它负责：

- 解析参数；
- 读取 JSON；
- 构造 `CompetitiveIntelRequest`；
- 加载 `config/agent_profiles.yaml`；
- 调用 `Orchestrator.run()`；
- 打印 summary；
- 可选写 Markdown 报告。

它不负责：

- 创建 Collector/Analyst/Writer/Reviewer；
- 手写 DAG；
- 直接操作 tool runtime；
- 直接处理 artifact flow。

这样 CLI 不会变成第二套 orchestrator。

---

## 3. 命令参数

模块 14 支持：

```text
competitive-intel run \
  --input tests/fixtures/request.json \
  --config config/agent_profiles.yaml \
  --fake-model \
  --output out/report.md
```

参数含义：

- `--input`：请求 JSON，必填；
- `--config`：agent profile 配置，默认 `config/agent_profiles.yaml`；
- `--fake-model`：v0 显式使用本地 fake pipeline，不需要 API key；
- `--output`：把最新 `ReportDraft` 写成 Markdown。

---

## 4. 输出摘要

成功运行后会打印：

```text
Loaded request: tests/fixtures/request.json
Run id: run_xxx
Run status: approved
Sources: 2
Claims: 2
Report id: report_xxx_001
```

如果 Reviewer 返回了 feedback，还会打印：

```text
Review feedback: 1
```

这些字段足够做本地 smoke test，也方便面试演示时解释每次 run 的结果。

---

## 5. Markdown 输出

当传入：

```bash
--output out/report.md
```

CLI 会从 artifact store 里取最新 `ReportDraft`，按 sections 写成：

```markdown
# Competitive Intelligence Report

## Overview
...

## Sources
...
```

注意：CLI 只负责格式化输出，不负责生成报告内容。内容仍然来自 Writer Agent 保存的 `ReportDraft`。

---

## 6. 错误处理

模块 14 要求命令行错误能读懂，而不是暴露 Python traceback。

当前处理：

- 输入文件不存在：argparse error；
- config 文件不存在：argparse error；
- JSON 解析失败：`invalid JSON`；
- request 结构不合法：`invalid request`。

这对“能用项目”很重要。真实用户第一次跑项目时，最常见问题就是路径错、JSON 写错、配置文件没找到。

---

## 7. 面试可以怎么讲

可以这样说：

> CLI 是整个系统的本地入口，但它刻意保持很薄。它只把外部输入转成 `CompetitiveIntelRequest`，把 config 转成 `AgentProfile`，然后调用 Orchestrator。真正的 pipeline 顺序、artifact flow、tool runtime 和 review feedback 处理都不在 CLI 里。这样同一套 Orchestrator 未来可以被 CLI、Web API 或任务队列复用。

重点强调：

- CLI 是 adapter，不是 workflow controller；
- Orchestrator 才是 pipeline owner；
- 一条命令可以跑完整 fake pipeline；
- 输出里有 run id、状态、source/claim/report 信息，方便调试和演示。

---

## 8. 测试覆盖

当前测试覆盖：

```text
test_cli_run_prints_human_readable_summary
test_cli_run_rejects_invalid_json
test_cli_run_accepts_config_and_fake_model_flags
test_cli_run_writes_markdown_report
test_cli_module_runs_with_fixture
```

这些测试保证 CLI 不只是“能 import”，而是真的能通过子进程运行完整本地 pipeline。
