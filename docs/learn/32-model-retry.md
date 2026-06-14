# 学习文档 32：ModelRuntime 重试机制 — 区分错误类型的指数退避

## 一句话概括

**`ModelRuntime.complete()` 现在对 provider 调用做最多 3 次指数退避重试（1s/2s/4s），但只对真正能恢复的错误（429/5xx/网络抖动）重试，4xx 客户端错误不重试 — 防止网络抖一下就触发整轮 fake fallback。**

## 为什么需要它

### 触发本次改动的真实场景

之前 `ModelRuntime.complete()` 的实现：

```python
try:
    raw = self._provider.complete(request)
except Exception as exc:
    return ModelResponse(ok=False, error=str(exc))
```

一次抖动 → `ok=False` → 调用方（`AnalystAgent` / `ReviewerAgent` / ...）`if not resp.ok or not resp.parsed: return []` → agent 返回空 result → harness 没拿到产物 → orchestrator 把那一轮当 stall 处理 → 整个 run 退化到 template fallback 写出 `[FAKE]` 报告。

实际产线场景里 429/503 抖一下完全可以恢复，没理由让一次抖动毁整个 run。

### 为什么不是无脑全重试

新手做法：

```python
for _ in range(3):
    try:
        return provider.complete(request)
    except Exception:
        time.sleep(1)
```

三个问题：

1. **4xx 错误也重试**：API key 错了、payload 格式错了，重试 3 次只是把同样的错误吞 3 次，徒增延迟
2. **固定 backoff**：上游被打挂时每秒一次重试 = 1 RPS 流量打死它，恶化雪崩
3. **`Exception` 太广**：用户的 `KeyboardInterrupt`、断言失败也吞掉了

### 新设计：错误分类 + 指数退避

```
errors raised by JsonPostTransport
  ├─ HTTPError(code=4xx 非 408/425/429)  → NonRetryableProviderError
  ├─ HTTPError(code=429/5xx/408/425)    → RetryableProviderError
  ├─ URLError / OSError / TimeoutError  → RetryableProviderError
  └─ JSONDecodeError (truncated body)   → RetryableProviderError

ModelRuntime.complete():
  for attempt in 0..max_retries:
    call provider
    on RetryableProviderError → sleep(min(base*2^attempt, max)) → retry
    on NonRetryableProviderError → return ok=False immediately
    on other Exception → return ok=False immediately (不能分类，不重试)
```

## 关键代码

```python
# src/competitive_intel_agents/runtime/model_runtime.py

class RetryableProviderError(ProviderError):
    """Transient — caller may retry after backoff."""

class NonRetryableProviderError(ProviderError):
    """Permanent — retrying will not help."""

_RETRYABLE_HTTP_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class JsonPostTransport:
    def post_json(self, url, headers, payload, timeout=30.0):
        ...
        try:
            with urlopen(req, ...) as response:
                return json.loads(response.read())
        except error.HTTPError as exc:
            if exc.code in _RETRYABLE_HTTP_CODES:
                raise RetryableProviderError(...) from exc
            raise NonRetryableProviderError(...) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise RetryableProviderError(...) from exc
        except JSONDecodeError as exc:
            raise RetryableProviderError(...) from exc


class ModelRuntime:
    def __init__(
        self,
        provider=None,
        max_retries=3,
        backoff_base=1.0,
        backoff_max=8.0,
        sleep=None,
    ):
        ...
        self._sleep = sleep or time.sleep   # 注入点：测试用 spy

    def complete(self, request):
        attempt = 0
        while True:
            try:
                raw = self._provider.complete(request)
                break
            except RetryableProviderError as exc:
                if attempt >= self._max_retries:
                    return ModelResponse(ok=False, error=str(exc))
                self._sleep(min(self._backoff_base * (2 ** attempt), self._backoff_max))
                attempt += 1
                continue
            except NonRetryableProviderError as exc:
                return ModelResponse(ok=False, error=str(exc))
            except Exception as exc:
                return ModelResponse(ok=False, error=str(exc))
        ...
```

## 设计取舍

### 为什么把分类放在 transport 层而不是 provider 层

`AnthropicMessagesProvider` 和 `HttpModelProvider` 共用同一个 `JsonPostTransport`。错误分类逻辑放在 transport 里，两个 provider 自动受益、无需各自实现一遍。Anthropic 和 OpenAI 都是 RESTful HTTP，错误语义一致 — 保持单点。

如果未来加 grpc/websocket provider，那时再让 provider 自己处理错误类型，也只是新增一条路径。

### 为什么 408/425 也算 retryable

`408 Request Timeout` 是上游告诉你"我没等到你的请求体"，`425 Too Early` 是 TLS 0-RTT 重放保护 — 都是网络层的偶发问题，重试一定要做。

429（限流）和 5xx 是经典 retryable case 不必赘述。

### 为什么 `JSONDecodeError` 是 retryable

当上游连接中途被掐断（超时、连接重置），urllib 可能拿到一段 partial body 返回成功状态，json.loads 失败。这种"半截响应"重试一次大概率能恢复。如果是真的协议层不兼容（API 改格式了），三次重试都失败后照样 `ok=False` 给上游报错，没掩盖真问题。

### 为什么默认 3 次而不是 5 次

3 次重试 + 1 次原始 = 4 次总尝试。退避 1+2+4 = 7s。一次 model 调用最坏耗时 ~7s+实际请求时间。如果再多重试，单次 model 调用就可能拖到 30s 以上，跟 #11 的全局 10 分钟超时挤占预算太狠。3 次是经验上"恢复 90% 瞬时错误"和"延迟可控"的甜区。

可以通过 `max_retries=5` 参数显式提高，但默认值要保守。

### 为什么用注入的 sleep

```python
runtime = ModelRuntime(provider=..., sleep=sleeps.append)
```

测试不用真的等 7 秒。`sleeps.append` 是一个普通的 `list.append` 当 spy 用，断言 `sleeps == [1.0, 2.0, 4.0]` 直接验证退避序列正确。

这是依赖注入的标准玩法，相比 `mock.patch("time.sleep")` 更干净（不破坏全局）。

### 为什么 `except Exception` 不重试

最后那个 catch-all 兜的是：

- 自定义测试 provider 抛了 `ValueError`、`KeyError` 之类
- provider SDK 自己抛了未分类异常

这些没法判断 retryable，盲目重试可能把幂等性搞坏（比如 provider 实际 commit 了一次 transaction 但客户端没收到响应）。所以采取保守策略：不分类 → 不重试 → 立刻报错让上游知道。

### 跟 harness 自带的 round 重试是什么关系

`RuntimeHarness` 有 `_max_retries=2` 用于 stall/error 信号触发整轮 agent 重跑，那是**业务层**的重试（agent 没拿到 tool 结果、模型给了空 response）。

`ModelRuntime` 的重试是**调用层**的重试（model API 抖一下）。

两层是正交的：调用层先尝试 4 次（1+3），都失败后业务层看到 `ok=False` 决定要不要再重新跑一轮 agent。一个负责"网络抖动恢复"，一个负责"业务结果异常恢复"。

## 测试

`tests/unit/test_model_runtime.py` 加了 5 个新测试：

1. `test_model_runtime_retries_on_retryable_error_then_succeeds` — 头两次抛 retryable，第三次成功，断言 `provider.calls == 3` 且 `sleeps == [1.0, 2.0]`
2. `test_model_runtime_does_not_retry_on_non_retryable` — 抛 NonRetryable，断言 `provider.calls == 1` 且 `sleeps == []`
3. `test_model_runtime_returns_failed_after_exhausting_retries` — 一直抛 retryable，断言 4 次调用、`sleeps == [1.0, 2.0, 4.0]`、最终 `ok=False`
4. `test_json_post_transport_classifies_429_as_retryable` — mock urlopen 抛 HTTPError(429)，断言转化为 `RetryableProviderError`
5. `test_json_post_transport_classifies_400_as_non_retryable` — mock urlopen 抛 HTTPError(400)，断言转化为 `NonRetryableProviderError`

## 面试要点

1. **重试要分类**：retryable / non-retryable / unknown 三类不同处理 — 4xx 不重试是基本素养，否则 100 个失败请求只是变成 300 个失败请求
2. **指数退避不是装饰**：固定间隔 1RPS 重试本身可以打挂上游，指数退避（+ jitter）是限流保护的一部分
3. **测试用注入 sleep 而非 mock 全局** — 接口里把 `sleep` 暴露成可注入参数，测试不需要等真实时间也不污染其他测试
4. **业务重试 vs 调用重试是不同层** — harness 的 round 重试和 ModelRuntime 的 API 重试不要混为一谈，各管各的语义
5. **跟 [[33-global-timeout]] 的预算关系**：单次 model 调用最坏 ~7s 退避（3 次），是 10 分钟超时预算的可控开销；如果默认 max_retries 设到 10，那单次调用就可能吃掉 1023s = 17 分钟，会让超时机制无效
