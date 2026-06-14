# 模块 32：ModelRuntime 重试机制

## Goal

Insulate the rest of the pipeline from transient model-provider failures
(429 / 5xx / network jitter) so a brief upstream blip no longer
collapses the entire run into the `[FAKE]` template fallback path.

## Scope

In scope:

- New error classes `ProviderError` / `RetryableProviderError` /
  `NonRetryableProviderError` exported from `runtime.model_runtime`
- `JsonPostTransport.post_json()` raises typed errors instead of bare
  `RuntimeError`
- `ModelRuntime.complete()` retries `RetryableProviderError` with
  exponential backoff; non-retryable errors and unknown exceptions fail
  fast
- 5 new unit tests in `tests/unit/test_model_runtime.py`

Out of scope:

- Changes to provider classes (`AnthropicMessagesProvider`,
  `HttpModelProvider`) — they continue to use `JsonPostTransport`
  unmodified
- Changes to `FakeModelProvider` — never raises
- Per-agent retry budgets — the same retry policy applies to all model
  calls; per-agent tuning would live on `AgentProfile` later if needed
- Concurrency / circuit-breaker primitives

## Design

### Error taxonomy

```
RuntimeError
└── ProviderError                          # base, exported
    ├── RetryableProviderError             # 408/425/429/5xx, network IO, JSON decode
    └── NonRetryableProviderError          # 4xx (auth, format, model-not-found)
```

Mapping in `JsonPostTransport.post_json()`:

| Source                                  | Mapped to                  |
|-----------------------------------------|----------------------------|
| `HTTPError(code in {408,425,429,500-504})` | `RetryableProviderError`    |
| `HTTPError(other 4xx)`                   | `NonRetryableProviderError` |
| `URLError` / `OSError` / `TimeoutError`   | `RetryableProviderError`    |
| `JSONDecodeError`                        | `RetryableProviderError`    |

`JSONDecodeError` is mapped retryable because the most common cause is
a partial body from a connection that was reset mid-stream — retrying
typically recovers; a real protocol mismatch fails the same way three
times and surfaces as `ok=False` after retries are exhausted.

### Retry loop

```python
ModelRuntime(
    provider,
    max_retries=3,        # 1 initial + 3 retries = 4 attempts max
    backoff_base=1.0,
    backoff_max=8.0,
    sleep=time.sleep,     # injected for tests
)
```

Backoff schedule: `min(backoff_base * 2**attempt, backoff_max)` →
`1.0s, 2.0s, 4.0s`, capped at `8.0s`.

```
attempt=0  call → RetryableError         → sleep(1)  → attempt=1
attempt=1  call → RetryableError         → sleep(2)  → attempt=2
attempt=2  call → RetryableError         → sleep(4)  → attempt=3
attempt=3  call → RetryableError         → return ok=False
```

`NonRetryableProviderError` and any other `Exception` short-circuit
immediately to `ModelResponse(ok=False, error=…)`.

## Tests

`tests/unit/test_model_runtime.py`:

1. `test_model_runtime_retries_on_retryable_error_then_succeeds` —
   scripted provider yields two retryable failures then a success;
   asserts 3 calls and `sleeps == [1.0, 2.0]`
2. `test_model_runtime_does_not_retry_on_non_retryable` — scripted
   provider yields `NonRetryableProviderError`; asserts 1 call,
   `sleeps == []`, `ok=False`
3. `test_model_runtime_returns_failed_after_exhausting_retries` —
   scripted provider always raises; asserts 4 calls,
   `sleeps == [1.0, 2.0, 4.0]`, final `ok=False`
4. `test_json_post_transport_classifies_429_as_retryable` — patches
   `urlopen` to raise `HTTPError(429)`; asserts `RetryableProviderError`
5. `test_json_post_transport_classifies_400_as_non_retryable` —
   patches `urlopen` to raise `HTTPError(400)`; asserts
   `NonRetryableProviderError`

## Backward compatibility

- `ModelRuntime(provider=...)` continues to work without specifying
  retry params; defaults yield the documented behavior
- Existing tests that use a provider raising plain `RuntimeError`
  (`test_provider_errors_become_failed_response`) still pass — generic
  exceptions remain non-retryable and surface as `ok=False`
- The `RuntimeError` base class of the new typed errors keeps any
  `except RuntimeError:` catch sites working identically
