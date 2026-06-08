# 模块 26：集成式 Rework Orchestration

## 目标

让 Reviewer 的可路由反馈成为正常 orchestrator run 的一部分。默认仍保持 v0 行为：返回 `needs_rework`。当显式启用 `enable_rework=True` 时，orchestrator 会自动调用 `ReworkLoop` 做 bounded repair。

## 当前实现

- `Orchestrator(enable_rework=True, max_rework_attempts=2)`
  - reviewer 返回 `rework` 时进入 `_apply_integrated_rework`。
  - 每次只处理当前 feedback 列表中的第一条，避免复杂并行修复。
  - 调用已有 `ReworkLoop`，复用 artifact lineage 和 route 规则。
- 终态：
  - `approved`：rework route 的 reviewer 最终 stop。
  - `needs_rework`：未启用集成 rework 时保持原行为。
  - `rework_failed`：超过尝试次数或 `ReworkLoop` 拒绝继续。
  - `aborted`：非 rework agent/harness abort。
- 审计：
  - 真实 `RuntimeHarness` 会继续写入 rework route 的 journal events。
  - 替身 harness 场景下，orchestrator 也会读取 `ReworkResult.final_decision`，不强依赖 journal。

## 架构边界

Orchestrator 不直接改 artifacts，不自己决定如何修复。它只把 reviewer feedback 交给 `ReworkLoop`，然后根据 route 的最终 reviewer 决策生成 run-level status。

## 当前取舍

- 每轮只处理一条 feedback，后续模块可以扩展为多 feedback plan。
- 不做人类编辑介入。
- 不并行 rerun stage，保持审计顺序简单。

## 测试

- `tests/unit/test_orchestrator.py`
  - 默认 rework 仍返回 `needs_rework`。
  - 启用 `enable_rework=True` 后，成功 rework 返回 `approved`。
  - 超过 attempts 后返回 `rework_failed`。
- `tests/unit/test_rework_loop.py`
  - 继续覆盖 route、artifact supersedes、下游 stale artifact reject。

## 完成标准

- 正常 run 可以自动修复 fixable reviewer feedback。
- 返工不会覆盖旧 artifact。
- run-level status 能区分未启用 rework、rework 成功、rework 失败。
