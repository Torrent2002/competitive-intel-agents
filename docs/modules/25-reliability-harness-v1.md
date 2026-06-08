# 模块 25：Reliability Harness v1

## 目标

把 RuntimeHarness 从“只管 round budget 和重复工具调用”增强为可诊断的运行控制层：工具结果要进 journal，stall 要能识别，retry 超限要给出明确健康信号，checkpoint 可以作为恢复入口。

## 当前实现

- `RoundEvent.tool_results`
  - 每轮执行过的工具结果会随 journal event 保存。
  - 失败工具会保留 `tool_call_id/error/preview`。
- Stall 检测
  - 如果 agent 没完成、没工具调用、没产物输出，并且不是 reviewer rework，就标记 `stalled_round`。
- Retry policy
  - `RuntimeHarness(max_retries=...)` 控制错误/停滞重试次数。
  - 超限后事件信号包含 `max_retries_exceeded`，decision 为 `abort`。
- Checkpoint resume
  - 如果 checkpoint store 里已有该 run/agent 的最新 checkpoint，下一次 `run_agent` 从 `latest.round + 1` 开始。
  - 恢复轮次信号包含 `resumed_from_checkpoint:<checkpoint_id>`。
- 非重试错误
  - agent 可通过 `non_retryable_error` signal 直接 abort。

## 架构边界

Harness 只负责运行控制、工具执行、journal 和 checkpoint。它不理解竞品分析业务，也不直接修改 artifacts。业务修复仍由 rework/orchestrator/agent 负责。

## 当前取舍

- retry 不做指数退避，因为当前运行是同步本地流程。
- checkpoint recovery 先做到 round 级恢复，不恢复 agent 内部复杂私有状态。
- stall 判断保持保守：有工具调用或有产物输出就不算 stall。

## 测试

- `tests/unit/test_reliability_harness_v1.py`
  - 只读停滞 round 会产生 `stalled_round`，超 retry 后 abort。
  - tool results 会进入 `RoundEvent.tool_results`。
  - harness 可从最新 checkpoint 的下一轮恢复。

## 完成标准

- harness 失败原因可以被 dashboard/golden/provenance 读取。
- 工具失败不再只是一条 signal，而有结构化结果可查。
- selected mid-run recovery 不需要从第一轮重新开始。
