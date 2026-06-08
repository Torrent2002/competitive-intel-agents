# 学习文档 26：集成式 Rework Orchestration

## 一句话概括

模块 26 把 Reviewer 的 feedback 自动接回正常 run：启用 `enable_rework=True` 后，orchestrator 会调用 `ReworkLoop` 做 bounded repair。

## 为什么需要它

之前的 ReworkLoop 已经能按 feedback 修复 artifact，但它还不是正常 run 的一部分。用户看到 `needs_rework` 后，需要额外手动触发。模块 26 解决这个断点。

## 关键代码

- `src/competitive_intel_agents/orchestrator/__init__.py`
  - `Orchestrator(enable_rework=True, max_rework_attempts=2)`
  - `_apply_integrated_rework(...)`
- `src/competitive_intel_agents/rework/__init__.py`
  - 继续负责 route、artifact replacement、supersedes/reject。

## 面试怎么讲

可以说：

> Orchestrator 不自己修 artifact，它只识别 reviewer 的 rework 决策，并把结构化 feedback 交给 ReworkLoop。ReworkLoop 负责按 target_agent 选择重跑路径，并保留 artifact lineage。这就是我们区别于单 agent 的地方：反馈不是一句自然语言建议，而是可以机器路由的协作协议。

## 后续扩展

- 多 feedback planning。
- 人类确认后再 rework。
- rework attempt metadata 持久化到 workspace。
- report export 标注 rework 历史。
