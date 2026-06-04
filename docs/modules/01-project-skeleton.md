# 01 Project Skeleton

## Goal

Create the repository layout for a Python package that can support agents, runtime execution, harness logic, journals, artifacts, configuration, and tests.

## Scope

In scope:

- Python package layout under `src/`.
- Test layout under `tests/`.
- Fixture layout under `tests/fixtures/`.
- Config layout under `config/`.
- Basic packaging files.

Out of scope:

- Real agent logic.
- Real model calls.
- Real persistence beyond placeholder modules.

## Expected Structure

```text
src/
  competitive_intel_agents/
    agents/
    artifacts/
    cli/
    dashboard/
    harness/
    journal/
    orchestrator/
    runtime/
config/
  agent_profiles.yaml
tests/
  fixtures/
    request.json
  unit/
  golden/
```

## Public Contract

The package should be importable:

```python
import competitive_intel_agents
```

The CLI command should be registered, even if it only runs a fake pipeline at first:

```text
competitive-intel run --input tests/fixtures/request.json
```

## Suggested Files

- `pyproject.toml`
- `src/competitive_intel_agents/__init__.py`
- `config/agent_profiles.yaml`
- `tests/fixtures/request.json`
- `tests/unit/test_imports.py`

## Tests

- Verify the package imports.
- Verify expected top-level modules import.
- Verify `config/agent_profiles.yaml` exists.
- Verify `tests/fixtures/request.json` exists and has valid JSON.

## Done Criteria

- `pytest` runs.
- Package imports from a clean checkout.
- CLI entrypoint is registered.
- No agent behavior is implemented yet.

## 中文学习笔记

### 一句话定位

Project Skeleton 不是在实现业务逻辑，而是在给整个项目搭一个可测试、可导入、可扩展的 Python 工程骨架。

### 面试中怎么讲

我会先把多 agent 系统拆成清晰的工程边界，而不是一开始就写 agent 逻辑。第一步做的是项目骨架：用 `src/` layout 放 Python package，用 `config/` 放 agent profile，用 `tests/` 放单元测试和 fixture，用 `pyproject.toml` 定义包元数据和 CLI entrypoint。

这样做的好处是，后面的 Collector、Analyst、Harness、Journal、Artifact Store 都有稳定的模块位置。任何模块都可以被测试直接 import，避免后期出现路径混乱、模块互相依赖不清的问题。

### 关键设计点

- `src/competitive_intel_agents/` 是正式包入口，后续所有生产代码都放这里。
- `pyproject.toml` 负责声明包名、Python 版本、测试配置和 CLI 命令。
- `config/agent_profiles.yaml` 先定义每个 agent 的预算、工具权限和策略，为 harness 做预算控制打基础。
- `tests/fixtures/request.json` 是后续 fake pipeline 和 golden replay 的最小输入样例。
- CLI 现在只做薄入口，不实现业务逻辑，后续会委托给 Orchestrator。

### 可以被追问时怎么答

如果面试官问为什么用 `src/` layout，可以说：它能防止测试时误 import 当前目录里的源码，逼迫我们像真实安装包一样导入模块，更容易暴露 packaging 问题。

如果问为什么第一步就做 CLI，可以说：CLI 是端到端 smoke test 的入口，但它应该保持很薄，只负责解析输入和调用 Orchestrator，不把业务逻辑塞进去。

如果问这个阶段为什么没有 agent 逻辑，可以说：这是刻意控制范围。Project Skeleton 的目标是让项目可导入、可测试、可运行，而不是提前写未定义边界的业务代码。
