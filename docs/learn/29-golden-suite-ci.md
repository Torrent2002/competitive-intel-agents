# 学习文档 29：Golden Suite Expansion and CI

## 一句话概括

模块 29 把 golden replay 从一个冒烟 case 扩展为 5 种 pipeline 场景的回归套件，并通过 CLI 命令输出 CI 友好的 pass/fail 信号。

## 为什么需要它

模块 17 的 golden replay 验证了"能跑通一次"。但真实项目的回归需要覆盖：

- **不同输入组合**：单个/多个竞品、有无问题。
- **边界情况**：sparse data、reviewer rejection。
- **CI 集成**：每次 push 自动检查核心 pipeline 不退化。

5 个 golden case 覆盖了不同的输入模式，任何一个退化都会导致 `competitive-intel golden` exit non-zero。

## 关键代码

- `src/competitive_intel_agents/golden/__init__.py`
  - `GoldenReplayRunner` — 从 root 目录加载所有 golden case，逐一运行。
  - `evaluate_golden_metrics()` — 对比 15 项结构化指标。
  - `ExpectedMetrics` — 支持 min/max ranges、required fields、boolean checks。

### 5 个 Golden Cases

| Case | 场景 | 验证点 |
|---|---|---|
| `case_01_single_competitor` | 单竞品、2 个问题 | 基准 happy path |
| `case_02_multi_competitor` | 2 个竞品、3 个问题 | 多竞品处理 |
| `case_03_sparse_sources` | 无竞品、1 个问题 | 稀疏数据不崩溃 |
| `case_04_reviewer_rejection` | enterprise + security 关注 | reviewer 运行且无异常拒绝 |
| `case_05_rework_success` | 3 个竞品、3 个问题 | 复杂输入稳定输出 |

### CLI 集成

```bash
# 运行所有 golden cases
competitive-intel golden --root tests/golden
# Exit 0 = 全部通过, Exit 1 = 有退化
```

失败时输出每个退化指标的名称、期望值和实际值。

## 面试怎么讲

可以说：

> 我们不做 exact text comparison，因为文本在 fake mode 下每次可能不同。Golden replay 检查的是结构化指标：source 数量不低于阈值、claim 覆盖率达标、reviewer 运行了、artifact lineage 有效、tool calls 不超限、总轮次在预算内。这些指标即便在 provider-backed 模式下也能检查，所以 golden suite 既能用 fake mode 做快速 CI，也能切换到真实 provider 做端到端回归。

## 后续扩展

- Chart-style CI 输出（junit xml）。
- 指标趋势追踪（golden metrics history 可视化）。
- Provider-backed 模式下的 golden baseline。
- 自动生成新 case 的工具。
