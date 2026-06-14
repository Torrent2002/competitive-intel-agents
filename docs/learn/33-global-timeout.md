# 学习文档 33：全局运行超时 — 用 monotonic 与 caveats 软兜底

## 一句话概括

**`Orchestrator` 现在接受 `max_wall_time`（默认 600s）参数，每跨越一个 agent 边界检查 monotonic 时钟；超时时如果已经写出 report 就走 `approved_with_caveats` 把残篇交付出去，否则 `aborted` — 杜绝 collector 死循环或 model 挂起把整个 run 卡到无限。**

## 为什么需要它

### 触发改动的真实场景

之前 `Orchestrator.run()` 没有任何 wall clock 检查。出问题路径：

1. collector 进入 abort loop（已经被 escape hatch 修过，但根本原因没解决）
2. model API 卡住但底层 socket 没超时（运营商/CDN 中间设备保持连接）
3. 单轮 reviewer rework 三次都不收敛 + 每次重试间隔很长

→ run 永远停留在 `running` 状态。Web UI `<meta refresh="2">` 一直转，dashboard 列表显示 N 小时的 zombie run，artifacts 一直锁着。

### 为什么不简单 `signal.alarm`？

最朴素的实现是 SIGALRM：

```python
signal.alarm(600)   # 600s 后给主线程发 SIGALRM
try:
    run()
finally:
    signal.alarm(0)
```

问题：

1. **不能在线程里用**：web dashboard 是 `ThreadingHTTPServer`，每个 run 在子线程跑，`signal` 只能在主线程设置
2. **粒度太粗**：信号在任何位置打断，可能让 artifact store 写到一半数据库连接断了，留下脏数据
3. **不可测**：测试不可能等 600s

需要一个**协作式**的超时检查：在已知安全的边界点（agent 之间、rework 迭代之间）主动检查时钟。

### 为什么粒度选在 agent 边界

权衡：

| 粒度 | 检查频率 | 死锁救援能力 | 实现成本 |
|------|----------|--------------|----------|
| 每条 model 调用前 | ~10/agent | 强 | 改 ModelRuntime |
| 每个 round 前 | ~3/agent | 中 | 改 RuntimeHarness |
| 每个 agent 前 | 4/run | 中弱 | 改 Orchestrator |
| 整 run 跑完后 | 1/run | 无 | trivial |

agent 边界 + rework 迭代起点的组合 = 在 4-12 个检查点上看时钟，足够拦住"卡 30 分钟才发现"的灾难，又不会污染 hot path。

如果想要更细，未来可以把 `_timeout_result_if_due` 注入到 harness 的 round loop（接口已经备好）。

### 为什么 `time.monotonic` 而不是 `time.time`

`time.time()` 是 wall clock — 系统时间被 NTP 调整、夏令时切换、用户手动改时间，都会让 deadline 跳动甚至倒退。

`time.monotonic()` 严格单增、不受系统时间影响，**就是为这种"距离起点的时间差"设计的**。Stdlib 里 `concurrent.futures.Future.result(timeout=)`、`threading.Lock.acquire(timeout=)` 都用 monotonic，没有理由我们这里偏离。

## 关键代码

```python
# src/competitive_intel_agents/orchestrator/__init__.py

class Orchestrator:
    def __init__(
        self, ...,
        max_wall_time: float | None = 600.0,
        time_provider: Callable[[], float] | None = None,
    ):
        ...
        self._max_wall_time = max_wall_time
        self._time_provider = time_provider or time.monotonic
        self._deadline: float | None = None

    def run(self, request):
        context = ...
        if self._max_wall_time is not None:
            self._deadline = self._time_provider() + self._max_wall_time
        else:
            self._deadline = None

        for agent in self._build_agents():
            timeout_result = self._timeout_result_if_due(context)
            if timeout_result is not None:
                return timeout_result
            result = self._harness.run_agent(context, agent)
            ...

        timeout_result = self._timeout_result_if_due(context)
        if timeout_result is not None:
            return timeout_result
        return RunResult(status="approved", ...)

    def _timeout_result_if_due(self, context):
        if self._deadline is None:
            return None
        if self._time_provider() < self._deadline:
            return None
        report_id = self._latest_report_id(context.run_id)
        timeout_caveat = ReviewFeedback(
            issue="format_violation",
            target_agent="reviewer",
            target_artifact_id=f"run_{context.run_id}_deadline",
            message=f"Run exceeded the configured wall-clock budget ({self._max_wall_time:.0f}s). ...",
            required_action="Review remaining gaps; rerun with a larger max_wall_time if deeper coverage is needed.",
            severity="advisory",
            blocking=False,
        )
        if report_id is not None:
            return RunResult(
                run_id=context.run_id,
                status="approved_with_caveats",
                report_id=report_id,
                caveats=[timeout_caveat],
                error="global_timeout",
            )
        return RunResult(
            run_id=context.run_id,
            status="aborted",
            report_id=None,
            error="global_timeout",
        )
```

## 设计取舍

### 为什么超时后**复用** `approved_with_caveats` 而不是新加状态

考虑过加 `timed_out` 新状态。否决理由：

- CLI / Web / 反序列化 / 交互式 UI 全都要补 case，工作量大
- "超时但有 report" 的语义跟 [[31-approved-with-caveats]] 完全对齐：报告可交付，附带说明
- 用户视角：看到 caveats 列表，知道有一条"超时"，自己决定要不要 rerun。比看到一个新 status `timed_out` 然后还得点进去看哪儿超时更直观

如果未来真有人需要在状态层 dispatch（比如告警系统看到 `timed_out` 自动重试），可以靠 `result.error == "global_timeout"` 区分。**用 error 字段做次级分类**，不污染状态枚举。

### 为什么用 `format_violation` 作 issue

`ReviewFeedback.issue` 限定枚举（`VALID_REVIEW_ISSUES`）。可选项里没有 `timeout` / `incomplete`。改枚举要碰 reviewer prompt、structured output validator、所有 reviewer 测试 — 加一个状态比加一个值便宜。`format_violation` 语义最近："输出不符合预期格式（被截断了）"，不会误导用户。

未来如果引入更多 advisory feedback 类型，可以一次性扩 `VALID_REVIEW_ISSUES` 加入 `incomplete_run` 或 `truncated_output`。

### 为什么 `caveat.blocking=False` 和 `severity="advisory"`

之前 [[31-approved-with-caveats]] 的设计：reviewer 全默认 `blocking=True`、`severity="blocking"`，所以当时有过"reviewer 暂时还产不出 advisory 反馈，因此 caveats 必须从残留 blocker 推断"的妥协。

这次的 timeout caveat 是 orchestrator 自己合成的，可以直接打成 advisory：

- 显式声明这是非阻断的告知性反馈
- 给未来 reviewer 学会输出 advisory 反馈时铺路 — 渲染层已经能区分 `blocking` 和 `advisory`，不用动

### 为什么 `CIA_MAX_RUN_SECONDS=0` 表示"无限"而不是"立即超时"

直觉是 0 = 0s = 立即超时。但运维场景里 `CIA_MAX_RUN_SECONDS=0` 的诉求几乎全是"我在 debug，先关掉这个限制"。把 0 解释为"禁用"和 None 等价更友好。

```bash
# Production: 默认 600s
unset CIA_MAX_RUN_SECONDS

# Tight SLA: 5 min
export CIA_MAX_RUN_SECONDS=300

# Debugging: 不限制
export CIA_MAX_RUN_SECONDS=0
```

要"立即超时"的人会写 `CIA_MAX_RUN_SECONDS=0.001`，更明确。

### 为什么 `time_provider` 用闭包而不是类

```python
ticks = iter([0.0, 10_000.0, 10_001.0])
orchestrator = Orchestrator(time_provider=lambda: next(ticks), ...)
```

测试需要时钟"按调用次数前进"，用 `iter()` + `next()` + `lambda` 三行就够了。比 `class FakeClock: def __init__(...): ... def __call__(...)` 短得多。

`time_provider: Callable[[], float]` 这个签名也跟 stdlib `concurrent.futures` 等用 monotonic 的风格一致。

## 测试

`tests/unit/test_orchestrator.py` 加了 3 个测试：

```python
def test_orchestrator_returns_aborted_when_timeout_before_any_report():
    ticks = iter([0.0, 10_000.0, ...])  # __init__ t=0, 立即跨过 deadline
    orchestrator = Orchestrator(
        harness=NoOpHarness(),
        max_wall_time=1.0,
        time_provider=lambda: next(ticks),
    )
    result = orchestrator.run(...)
    assert result.status == "aborted"
    assert result.error == "global_timeout"
    assert result.report_id is None

def test_orchestrator_returns_caveats_when_timeout_after_report_exists():
    # writer 写 report 之后 ticks 跨过 deadline
    # → reviewer 没机会跑就触发 timeout
    assert result.status == "approved_with_caveats"
    assert result.caveats[0].issue == "format_violation"
    assert "wall-clock budget" in result.caveats[0].message
    assert "reviewer" not in harness.calls

def test_orchestrator_no_timeout_when_max_wall_time_is_none():
    # 显式禁用超时，确认现有 fake pipeline 行为不变
    assert result.status == "approved"
```

## 面试要点

1. **wall clock 选 monotonic**：deadline 用 `time.monotonic`，永远不要用 `time.time` 做 timeout — NTP 跳变会让 deadline 漂移
2. **协作式超时优于信号超时**：`signal.alarm` 在多线程不可用、粒度粗、留脏数据；在已知边界主动检查更安全
3. **粒度选择是工程权衡**：每 model 调用前查太细、整 run 后才查无意义；agent 边界是甜区
4. **状态枚举要慎重扩充**：能复用 `approved_with_caveats` 就不要新加 `timed_out`；用 error 字段做次级分类不污染主状态机
5. **测试时钟用 iter+lambda 注入**：比 mock 全局或 fake class 都干净，签名 `Callable[[], float]` 跟 stdlib 风格一致
6. **跟 [[31-approved-with-caveats]] 的语义复用**：超时不是失败，是"预算到了 + 已交付的部分"，用现成的软终态承接最自然
