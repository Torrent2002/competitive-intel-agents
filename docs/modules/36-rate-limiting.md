# 模块 36：Per-engine 限速 + 429 自动降速

## Goal

把搜索 / fetch 通道从"无限速 + `time.sleep(random.uniform(0.3, 0.8))` 一刀切"
改造成 **per-engine token bucket**，并在 `HTTP 429` 时自动降速，避免在
真实环境跑 collector 时被搜索引擎封 IP 或被 Serper 限流。

## Scope

In scope:

- 新增 `runtime/rate_limiter.py`，实现 `TokenBucket`：
  cooperative（caller 主动 `acquire`）、`time_provider`/`sleep` 可注入、
  支持 `penalize(factor, duration)` 临时降速窗口
- 5 个 search adapter（`DuckDuckGoSearch` / `BingSearch` / `BaiduSearch`
  / `SogouSearch` / `SerperSearch`）入口加 `acquire`，错误路径检测
  `HTTP 429` / `Too Many Requests` 标记调 `penalize`
- `WebFetchTool` 加 per-domain bucket：未指定 host 的请求按
  `default_domain_rate=0.5`（每 host 2s 一次）
- `make_default_search_adapter` 用 `_default_search_rate_limiters`
  给每个 engine 装默认 bucket：DDG 1 rps、Bing/Baidu/Sogou 0.5 rps、
  Serper 10 rps
- `FallbackSearch` 移除 `time.sleep(random.uniform(0.3, 0.8))`：每个
  adapter 自己有 limiter，全局 jitter 不再需要
- 6 个新单元测试在 `tests/unit/test_rate_limiter.py`，
  4 个新单元测试在 `tests/unit/test_real_web_tools.py`
- `runtime/__init__.py` 导出 `TokenBucket`

Out of scope:

- 跨进程限速（in-memory bucket 仅限单实例；多实例部署需 Redis backend，
  follow-up issue）
- 持久化 penalize 状态（进程重启 token 计数归零，可接受）
- HTTP 429 重试（跟 [[32-model-retry]] 不同：search adapter 直接返回
  `[]` 让 fallback chain 走下一档；retry 留给 model 层）

## Design

### Token bucket

```
TokenBucket(rate_per_sec, burst, time_provider, sleep)
  ├── acquire():   refill → if tokens >= 1: consume; else sleep(deficit/rate)
  └── penalize(factor=0.5, duration=30s):
        _penalty_until = max(now + duration, _penalty_until)
        _penalty_factor = min(_penalty_factor, factor)   # 不 compound
```

Key choices:

- **Burst** 让前 N 个请求免等，避免每 run 头部耗时被均匀拉长
- **Penalty 不 compound**：重复 `penalize(0.5)` 仍是 0.5，只延长窗口。
  避免在反复 429 下把 effective rate 压到接近零、整个 run 卡死
- **Time injection**：跟 [[32-model-retry]] 一致的测试模式

### Adapter integration

```
adapter.search(query, limit):
  if rate_limiter: rate_limiter.acquire()
  try:
    raw = http_client.get_text(...)
  except Exception as exc:
    if rate_limiter and _looks_like_429(str(exc)):
      rate_limiter.penalize()
    return []
  return parse(raw)
```

`_looks_like_429` 用字符串包含检测（"429" 或 "too many requests"）。
HTML adapter 的 `HttpClient` / `BrowserHttpClient` 把 `urllib`/`curl_cffi`
异常包成 `RuntimeError("failed to fetch ...")`，没有结构化 status code，
所以只能从异常文本里捞。Serper 走自己的 `urllib`，能拿到结构化
`HTTPError.code == 429`，那条路径走精确判断。

### Per-domain WebFetch limiter

```
WebFetchTool.run(args):
  host = urlparse(url).hostname
  self._limiter_for(host).acquire()  # 缺则按需创建
  ...
```

每个 host 独立 bucket，第一次见到自动建。预先注入的 host 走
`domain_rate_limiters` 字典覆盖默认。

## Tests

`tests/unit/test_rate_limiter.py`（6 个新测试）：

1. `test_token_bucket_allows_burst_immediately` — burst=3 头三次零等待
2. `test_token_bucket_blocks_until_rate_allows_next_token` — 1 rps + burst=1，
   第二次 acquire 必须 sleep 1.0s
3. `test_token_bucket_penalize_halves_rate_temporarily` — penalize 后下次
   acquire 等 1.0s（vs 不 penalize 的 0.5s）
4. `test_token_bucket_penalty_expires_and_rate_recovers` — 窗口到期后
   gap 回到 0.5s
5. `test_token_bucket_rejects_invalid_arguments` — 各 ValueError 路径
6. `test_token_bucket_repeated_penalty_does_not_compound_factor` — 两次
   `penalize(0.5)` 仍按 0.5 算

`tests/unit/test_real_web_tools.py`（4 个新测试）：

7. `test_search_adapter_calls_rate_limiter_acquire_before_request` —
   DDG 注入 `_RecordingLimiter`，断言 `acquires == 1`
8. `test_serper_429_triggers_penalize_then_returns_empty` —
   `urllib_error.HTTPError(code=429)` → penalize 一次，返回 `[]`
9. `test_web_fetch_uses_per_domain_rate_limiter` — 同 host 两次 +
   不同 host 一次，断言对应 bucket `acquires` 计数正确
10. `test_web_fetch_penalizes_on_429` — 模拟 `RuntimeError("... HTTP 429 ...")`
    → host bucket penalize 一次，异常透传

## Backward compatibility

- 所有 adapter 的 `rate_limiter` 参数都默认 `None`：旧 caller 不传
  就是无限速行为，跟改动前一致
- `make_default_search_adapter()` 默认装 limiter，但内部 limiter
  在 fake/test 环境（time 不前进的 stub）会立刻放行 token，不阻塞
- `WebFetchTool` 的 `domain_rate_limiters` 默认 `None`，`default_domain_rate=0.5`
  开启自建 bucket。已有不传 host 的 url 不受影响（host 解析为空跳过 limiter）

## Related

- [[32-model-retry]] — model 层的 429 重试；search 层选择不重试，因为
  fallback chain 已经提供了切换 engine 的能力
- [[34-search-api-fallback]] — Serper 主通道 + HTML fallback；本模块
  让该结构在 429 下也能稳态运行
- [[37-structured-logging]] — `penalize` 事件后续可以借 logging 上报，
  方便 ops 监控限速触发频率
