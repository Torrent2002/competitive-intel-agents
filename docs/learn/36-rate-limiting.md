# 学习文档 36：Per-engine 限速 + 429 自动降速

## 一句话概括

**搜索 / fetch 通道改用 token bucket，每个 engine 独立 rate，HTTP 429 触发临时降速窗口。** 取代之前 `time.sleep(random.uniform(0.3, 0.8))` 一刀切的"用 jitter 假装是限速"的做法，让真实环境跑 collector 不再因为搜索引擎反爬或 Serper 配额触发整轮 run 失败。

## 为什么需要它

### 触发改动的真实场景

之前 collector 跑 飞书 vs 钉钉 case 时，前 5 次 `web_search` 一切正常，第 6 次 Bing 突然返回 0 results。看 stderr：

```
[bing] query='飞书 协作 价格' results=0 error=HTTP Error 429: Too Many Requests
```

后续每一次 search 都返 429，整个 collector 在那一轮拿不到任何 source，触发 [[35-claim-source-cross-check]] 之前的 `coverage_partial` 信号 → 反复 rework → 最终 `needs_more_evidence` 收场。

而代码层"限速"只有这一行：

```python
# FallbackSearch.search()
for adapter in self._adapters:
    time.sleep(random.uniform(0.3, 0.8))  # ← 唯一节流
    results = adapter.search(query, limit=limit)
```

这是**全局间 jitter**，不是限速：

1. 它只在不同 engine 之间停 0.3-0.8s，**同一 engine 连续多次 query 之间不停**（因为 collector 跑了 N 个不同 query，每个 query 内部都会调全部 engine）
2. 即便停了 jitter，"全局停 0.3s" 也跟"DDG 1 rps、Bing 0.5 rps"是两个不同的事 — 前者是搪塞，后者是限速

### 为什么不是直接固定 sleep

最简单的"限速"是给每个 adapter 加 `time.sleep(2)`：

| 方案 | 缺点 |
|------|------|
| 固定 `sleep(2)` 每次 | burst 也不允许：第一个 query 也要等 2s。10 个 query × 3 engine = 60s 无效等待 |
| `sleep(random.uniform(...))` 同上 | 抗反爬指纹效果可疑（搜索引擎 anti-bot 看 IP 频率，不看 micro-jitter） |
| Token bucket | burst 让头几次免等，长期 rate 受控，且支持"被服务方明确说慢"的反馈降速（penalize） |

### 为什么 429 要触发自动降速而不是退避一次就走

之前的代码 429 之后**完全无记忆**：下一次 query 还是按原速度发出，再吃 429，再退避。这一轮 run 内 Bing 会被反复打到 429，最后 collector 干脆放弃 Bing 路径。

正确做法是 429 触发 limiter `penalize` —— 给 Bing 一个 30s 的"软冷却"窗口，期间所有走 Bing bucket 的请求自动排得更稀。30s 后窗口到期自动恢复。**让限速器记住"这个 engine 现在被点名了"。**

## 关键代码

### 1. TokenBucket 核心

```python
# src/competitive_intel_agents/runtime/rate_limiter.py

class TokenBucket:
    def __init__(self, rate_per_sec, burst=1, time_provider=time.monotonic, sleep=time.sleep):
        self._rate = rate_per_sec
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time_provider()
        self._penalty_until = 0.0
        self._penalty_factor = 1.0

    def _effective_rate(self):
        now = self._time()
        if now >= self._penalty_until:
            self._penalty_factor = 1.0   # 自动恢复
            return self._rate
        return self._rate * self._penalty_factor

    def acquire(self):
        while True:
            now = self._time()
            elapsed = max(0.0, now - self._last_refill)
            self._tokens = min(self._burst,
                               self._tokens + elapsed * self._effective_rate())
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self._effective_rate()
            self._sleep(wait)

    def penalize(self, factor=0.5, duration=30.0):
        new_until = self._time() + duration
        if new_until > self._penalty_until:
            self._penalty_until = new_until
        self._penalty_factor = min(self._penalty_factor, factor)
```

### 2. Search adapter 接入

```python
# DuckDuckGoSearch.search
if self._rate_limiter is not None:
    self._rate_limiter.acquire()
try:
    html_text = self._http_client.get_text(...)
except Exception as exc:
    if self._rate_limiter is not None and _looks_like_429(str(exc)):
        self._rate_limiter.penalize()
    return []
```

`_looks_like_429` 用字符串检测，因为 HTML adapter 的 `HttpClient` 把异常包成 `RuntimeError("failed to fetch ...")`，没结构化 code。Serper 路径走自己的 `urllib`，能精确捕 `HTTPError.code == 429`。

### 3. Per-domain WebFetch

```python
# WebFetchTool.run
host = parse.urlparse(url).hostname or ""
if host:
    self._limiter_for(host).acquire()
try:
    html_text = self._http_client.get_text(url, timeout=self._timeout)
except Exception as exc:
    if host and _looks_like_429(str(exc)):
        self._limiter_for(host).penalize()
    raise
```

`_limiter_for(host)` 缓存策略：第一次见到的 host 按需创建一个默认 bucket（0.5 rps）；预先注入 `domain_rate_limiters={"x.com": ...}` 的 host 走预设值。

## 设计取舍

### 为什么 penalize 不 compound

最直觉的"被 429 一次就降一档"实现是 `factor *= 0.5`：第一次 429 → 0.5x，第二次 429 → 0.25x，第三次 429 → 0.125x。

**否决**：

1. 大型 engine 的 429 经常成串出现（因为前一波请求已经在路上了），10 秒内吃 5 次 429 = `0.5^5 = 3%` 的速率，整个 run 卡死
2. compound 的"恢复"也很慢，后续 30s 都是低速，错配实际情况
3. 简单的"取 min(0.5)"+ "延长窗口" 实际可观测的恢复时间是 30s，对真实场景已经够稳

代价：连续 429 时不会越压越狠。但 `penalize` 默认 30s 窗口已经长到能让大多数引擎冷静下来。

### 为什么 search 不重试 429（跟 model retry 不一样）

[[32-model-retry]] 里 model provider 的 429 是**重试 + 指数退避**，因为：
- 模型只有一家，不能 fallback
- 一次模型调用平均成本高（agent 的整轮 work 都依赖它）

Search 层不一样：
- 有 fallback chain（Serper → DDG → Bing），一个 engine 暂时没结果，下一个 engine 顶上
- 单次 search 调用便宜，重试的"价值"小于切换 engine

**所以 search adapter 的 429 路径直接 `return []`**，让 `FallbackSearch` 自然走下一档。`penalize` 是为了同一 engine 在**这一轮 run 里不要再被打**，不是当前这次调用要重试。

### 为什么 limiter 是 in-memory 不上 Redis

- 当前部署 = 单实例（[[39-deployment]] 还没做多实例）
- collector 是顺序跑的，没有 thread pool / asyncio 并发抢同一个 bucket
- 上 Redis 增加部署复杂度（要装 Redis + 网络 RTT）但不解决任何当前问题
- 多实例部署时再切换（follow-up）

### 为什么 burst > 1

观察：collector 一轮 run 大约发 6-10 次 search per engine。

如果 `burst=1, rate=1`：第 1 次免等，第 2-10 次 sleep 1s × 9 = 9s 累加延迟。

`burst=2, rate=1`：第 1-2 次免等，第 3-10 次 sleep 1s × 8 = 8s。差别不大但**头部体感**好（开始几次很快，给用户"在转"的及时反馈）。

### 为什么 _looks_like_429 用字符串检测

HTML adapter 的异常链：

```
urllib.error.HTTPError("HTTP Error 429: Too Many Requests")
  → wrapped in HttpClient: RuntimeError("failed to fetch <url>: HTTP Error 429: ...")
```

要拿到结构化 status code 只能改 `HttpClient.get_text` 的契约（让它返回 `(status, body)` 或抛自定义异常）—— 这个改动会扩散到所有调用方。**字符串检测的代价是边界 case 误判**（比如 URL 里恰好包含 "429"），但实际上：

1. 错误文本是程序自己生成的格式化字符串，受控
2. 误判后果只是多 penalize 一次，30s 后自动恢复，没有持久副作用
3. 不引入新的契约扩散

## 测试

`tests/unit/test_rate_limiter.py` 6 个：

1. `test_token_bucket_allows_burst_immediately` — burst=3 头三次零等待
2. `test_token_bucket_blocks_until_rate_allows_next_token` — 1 rps + burst=1，第二次 acquire 必须 sleep 1.0s
3. `test_token_bucket_penalize_halves_rate_temporarily` — penalize 后下次 acquire 等 1.0s（vs 不 penalize 的 0.5s）
4. `test_token_bucket_penalty_expires_and_rate_recovers` — 窗口到期后 gap 回到 0.5s
5. `test_token_bucket_rejects_invalid_arguments` — `rate_per_sec<=0`、`burst<1`、`factor∉(0,1]`、`duration<=0`
6. `test_token_bucket_repeated_penalty_does_not_compound_factor` — 两次 `penalize(0.5)` 仍按 0.5

`tests/unit/test_real_web_tools.py` 4 个：

7. `test_search_adapter_calls_rate_limiter_acquire_before_request` — DDG 注入 `_RecordingLimiter`，断言 `acquires == 1`
8. `test_serper_429_triggers_penalize_then_returns_empty` — `urllib_error.HTTPError(code=429)` → penalize 一次，返回 `[]`
9. `test_web_fetch_uses_per_domain_rate_limiter` — 同 host 两次 + 不同 host 一次，断言 `bucket_a.acquires == 2`、`bucket_b.acquires == 1`
10. `test_web_fetch_penalizes_on_429` — `RuntimeError("... HTTP 429 ...")` → host bucket penalize 一次，异常透传

## 面试要点

1. **限速 ≠ 全局 sleep**：`sleep(random.uniform)` 不是限速，是搪塞。真限速是 token bucket（leaky bucket、sliding window 也行）。考察候选人能不能识别这个区别。

2. **per-engine vs per-process**：搜索引擎反爬看你的 IP 对**这个引擎**的访问频率，不是你进程总频率。所以 limiter 必须 per-engine。WebFetch 同理：per-domain，不是 per-process。

3. **429 触发降速窗口比直接退避一次更稳**：因为后续请求很多还在路上，只退避一次的话会被反复打。30s 窗口给服务端时间冷静。

4. **penalize 不 compound 是关键决策**：连续 N 次 429 不要让 rate 指数下降，否则 run 会卡死。简单的"取 min(0.5) + 延长窗口"够用。

5. **time injection + sleep injection 让限速器可单测**：跟 [[32-model-retry]] 同模式，`FakeClock(now, sleeps=[])` 让 1.0s 的 sleep 在测试里 0 等待但行为可断言。

6. **不重试 vs fallback chain 的取舍**：模型层有重试因为没替代品；搜索层不重试因为有 fallback chain。决定"要不要重试"的真正问题不是异常类型，而是**有没有便宜的替代路径**。

7. **跟 [[34-search-api-fallback]] 的协同**：fallback chain 决定了"被一个 engine 拒了去找别的"；本模块决定了"在同一 engine 内部别打太密"。两者互补，缺一就会崩（前者没 fallback、后者持续打 → 全军覆没）。
