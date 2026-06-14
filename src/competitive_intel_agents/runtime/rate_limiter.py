"""In-process token-bucket rate limiter for outbound HTTP calls.

The collector pipeline issues search and fetch requests sequentially —
there is no thread pool — so a single-process bucket is enough to keep
DuckDuckGo / Bing / Baidu / Sogou below their tolerated rates and to
back off automatically when an engine returns ``HTTP 429``.

Design notes
------------
- Cooperative: callers must invoke :meth:`TokenBucket.acquire` before
  each outbound request. ``acquire`` sleeps until a token is available;
  it does not enforce anything by itself.
- Time and sleep are injected (``time_provider`` / ``sleep``) so unit
  tests can run instantaneously and assert on requested sleeps without
  wall-clock waits — same pattern :class:`ModelRuntime` uses for retry
  back-off.
- :meth:`penalize` is the 429 escape hatch. The effective rate is
  multiplied by ``factor`` (default 0.5) for ``duration`` seconds, then
  recovers automatically on the next ``acquire`` after the timestamp
  passes. Multiple successive penalties stack onto the same window
  rather than compounding the factor — keeps recovery predictable.
"""

from __future__ import annotations

import time
from typing import Callable


class TokenBucket:
    """Single-process token-bucket limiter.

    ``rate_per_sec`` is the steady-state rate in tokens per second. A
    burst of ``burst`` tokens is allowed before throttling kicks in,
    which keeps the first few requests of a run snappy.
    """

    def __init__(
        self,
        rate_per_sec: float,
        burst: int = 1,
        time_provider: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        if burst < 1:
            raise ValueError("burst must be at least 1")
        self._rate = float(rate_per_sec)
        self._burst = int(burst)
        self._time = time_provider
        self._sleep = sleep
        self._tokens = float(burst)
        self._last_refill = time_provider()
        # ``_penalty_until`` caps the effective rate at ``_rate * _penalty_factor``
        # while ``time() < _penalty_until``. After that point both reset.
        self._penalty_until = 0.0
        self._penalty_factor = 1.0

    def _effective_rate(self) -> float:
        now = self._time()
        if now >= self._penalty_until:
            # Window expired — restore full rate.
            self._penalty_factor = 1.0
            return self._rate
        return self._rate * self._penalty_factor

    def acquire(self) -> None:
        """Block until at least one token is available, then consume it."""
        while True:
            now = self._time()
            elapsed = max(0.0, now - self._last_refill)
            self._tokens = min(
                float(self._burst),
                self._tokens + elapsed * self._effective_rate(),
            )
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            # Need to wait until enough time has passed to earn a token.
            deficit = 1.0 - self._tokens
            wait = deficit / max(self._effective_rate(), 1e-9)
            self._sleep(wait)

    def penalize(self, factor: float = 0.5, duration: float = 30.0) -> None:
        """Halve (or otherwise scale) the effective rate for ``duration`` seconds.

        Called on ``HTTP 429`` to back off automatically without
        forcing the caller to track per-engine cooldowns. Stacking
        penalties before the previous window expires extends the
        ``_penalty_until`` deadline and keeps the lower factor — they
        do not compound (factor 0.5 followed by factor 0.5 stays at
        0.5, not 0.25), so recovery time stays predictable even when
        a service rate-limits aggressively.
        """
        if not (0.0 < factor <= 1.0):
            raise ValueError("factor must be in (0, 1]")
        if duration <= 0:
            raise ValueError("duration must be positive")
        now = self._time()
        new_until = now + duration
        if new_until > self._penalty_until:
            self._penalty_until = new_until
        # Keep the most aggressive factor we've been asked to apply.
        self._penalty_factor = min(self._penalty_factor, factor)


__all__ = ["TokenBucket"]
