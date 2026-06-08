# 01 Project Skeleton — 面试级学习笔记

## 一句话概括

**Project Skeleton 是把项目先做成一个可导入、可测试、可扩展的 Python 包，而不是一开始就把 agent 逻辑写进脚本里。**

---

## 1. 为什么第一步不是写 Agent？

如果一开始就写一个 `main.py` 调模型、搜资料、写报告，很快就会变成 demo：

- 模块边界不清楚；
- 单元测试不好写；
- CLI、orchestrator、agent、runtime 混在一起；
- 后续很难解释每个模块的职责；
- 面试时容易被认为只是 prompt glue。

这个项目的目标是做一个可审计的竞争情报 workflow，所以第一步先搭工程骨架，让后续每个模块都有明确位置。

---

## 2. 目录设计

```text
src/competitive_intel_agents/
  agents/        # Collector, Analyst, Writer, Reviewer
  artifacts/     # 结构化共享产物
  cli/           # 命令行入口
  dashboard/     # 后续观测界面
  harness/       # RuntimeHarness
  journal/       # 审计事件
  orchestrator/  # 端到端编排
  runtime/       # tool/model runtime
config/
  agent_profiles.yaml
tests/
  fixtures/
  unit/
  golden/
```

核心思路是：**按业务职责拆模块，而不是按“所有代码放一个脚本”组织。**

---

## 3. 为什么用 `src/` layout？

`src/` layout 能避免测试时误导入当前目录里的源码。测试必须像真实安装后的包一样导入：

```python
import competitive_intel_agents
```

这会更早暴露 packaging、module path、entrypoint 的问题。

面试里可以说：

> 我用 `src/` layout 是为了让测试环境更接近真实用户安装后的导入方式，避免本地路径偶然可用导致隐藏 packaging bug。

---

## 4. CLI 为什么这么早出现？

CLI 不是为了在第一步就跑完整业务，而是为了给端到端 smoke test 留入口：

```text
competitive-intel run --input tests/fixtures/request.json
```

当前 CLI 应该保持很薄，后续只调用 Orchestrator，不直接写业务逻辑。

这是一个重要边界：

- CLI 负责参数解析；
- Orchestrator 负责 workflow；
- Harness 负责 agent round 控制；
- Agent 负责各自 artifact。

---

## 5. 和后续模块的关系

Project Skeleton 给后续所有模块提供稳定位置：

- Core Models 可以放在 `models.py`；
- Agent Interface 放在 `agents/`；
- Journal Store 放在 `journal/`；
- Artifact Store 放在 `artifacts/`；
- Tool/Model Runtime 放在 `runtime/`；
- Harness 放在 `harness/`；
- Orchestrator 和 CLI 后续接起来。

这个阶段不实现 agent 行为，是刻意控制 scope。

---

## 6. 测试覆盖

```text
test_package_and_top_level_modules_import
test_agent_profiles_config_exists
test_request_fixture_exists_and_is_valid_json
test_cli_entrypoint_is_registered
test_cli_module_runs_with_fixture
```

这些测试不是业务测试，而是工程骨架测试：包能导入、配置存在、fixture 可读、CLI 入口可运行。

---

## 7. 面试追问

**Q: 为什么不先做功能？**

A: 因为这个项目强调可审计 workflow，不是一次性脚本。先搭骨架能让后续每个模块有清晰职责和测试入口。

**Q: 为什么 CLI 不直接实现 pipeline？**

A: CLI 应该是薄入口。真正的 pipeline 要放在 Orchestrator，否则 CLI 和业务逻辑会耦合，后续 web/dashboard 入口也没法复用。
