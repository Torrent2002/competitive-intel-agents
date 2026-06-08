# 学习文档 25：Reliability Harness v1

## 一句话概括

模块 25 让 harness 的失败更可诊断：工具结果进 journal，停滞轮次可识别，retry 超限有明确信号，checkpoint 可以恢复到下一轮。

## 为什么需要它

多 agent 系统的难点不是“跑成功一次”，而是失败时能解释：

- 哪个工具失败了？
- agent 是真的在推进，还是空转？
- retry 了几次？
- 能不能从 checkpoint 继续？

这些都应该由 harness 负责，而不是散落在每个 agent 里。

## 关键代码

- `src/competitive_intel_agents/harness/runtime.py`
  - `RoundEvent.tool_results`
  - `stalled_round`
  - `max_retries_exceeded`
  - `resumed_from_checkpoint:<id>`
  - `RuntimeHarness(max_retries=...)`

## 面试怎么讲

可以说：

> Harness 是系统的运行控制面，不懂业务，但负责预算、工具执行、错误转译、checkpoint 和 journal。这样 agent 写起来很薄，失败诊断也不会靠自然语言日志。

## 后续扩展

- retry backoff。
- checkpoint 持久化到 workspace。
- dashboard 展示 tool result preview。
- golden replay 增加 stall/retry 指标。
