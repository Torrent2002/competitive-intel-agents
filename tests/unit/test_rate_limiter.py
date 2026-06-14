"""Unit tests for ``TokenBucket`` rate limiter."""

from __future__ import annotations

import pytest

from competitive_intel_agents.runtime.rate_limiter import TokenBucket


class FakeClock:
    """Deterministic time + sleep stub for rate-limiter tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        # Sleep advances the fake clock so the next refill produces tokens.
        self.now += seconds


def test_token_bucket_allows_burst_immediately() -> None:
    """``burst`` tokens should be available without any sleep."""
    clock = FakeClock()
    bucket = TokenBucket(
        rate_per_sec=1.0,
        burst=3,
        time_provider=clock.time,
        sleep=clock.sleep,
    )

    bucket.acquire()
    bucket.acquire()
    bucket.acquire()

    assert clock.sleeps == []


def test_token_bucket_blocks_until_rate_allows_next_token() -> None:
    """Once the burst is exhausted the next acquire should sleep ~1/rate."""
    clock = FakeClock()
    bucket = TokenBucket(
        rate_per_sec=1.0,
        burst=1,
        time_provider=clock.time,
        sleep=clock.sleep,
    )

    # Burn the single burst token instantly.
    bucket.acquire()
    assert clock.sleeps == []

    # Second acquire must wait one full second at 1 rps.
    bucket.acquire()
    assert clock.sleeps == [1.0]


def test_token_bucket_penalize_halves_rate_temporarily() -> None:
    """``penalize`` should double the inter-request gap until the window ends."""
    clock = FakeClock()
    bucket = TokenBucket(
        rate_per_sec=2.0,  # 0.5s between tokens at full rate
        burst=1,
        time_provider=clock.time,
        sleep=clock.sleep,
    )
    bucket.acquire()
    bucket.penalize(factor=0.5, duration=30.0)

    # With a 30s window and effective rate 1.0/s, the next token costs 1s
    # rather than the unpenalized 0.5s.
    bucket.acquire()
    assert clock.sleeps == [1.0]


def test_token_bucket_penalty_expires_and_rate_recovers() -> None:
    """After the penalty window the bucket should refill at the full rate again."""
    clock = FakeClock()
    bucket = TokenBucket(
        rate_per_sec=2.0,
        burst=1,
        time_provider=clock.time,
        sleep=clock.sleep,
    )
    bucket.acquire()
    bucket.penalize(factor=0.5, duration=10.0)

    # Move past the penalty window without any acquires (e.g. quiet period).
    clock.now += 30.0
    # Burst token has refilled to 1 (capped), so this acquire is free.
    bucket.acquire()
    assert clock.sleeps == []

    # The next acquire should pay the *unpenalized* 0.5s gap, not 1.0s.
    bucket.acquire()
    assert clock.sleeps == [0.5]


def test_token_bucket_rejects_invalid_arguments() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate_per_sec=0)
    with pytest.raises(ValueError):
        TokenBucket(rate_per_sec=1.0, burst=0)

    bucket = TokenBucket(rate_per_sec=1.0, burst=1)
    with pytest.raises(ValueError):
        bucket.penalize(factor=0.0)
    with pytest.raises(ValueError):
        bucket.penalize(factor=1.5)
    with pytest.raises(ValueError):
        bucket.penalize(duration=0)


def test_token_bucket_repeated_penalty_does_not_compound_factor() -> None:
    """Stacking penalties extends the window but keeps factor predictable."""
    clock = FakeClock()
    bucket = TokenBucket(
        rate_per_sec=2.0,
        burst=1,
        time_provider=clock.time,
        sleep=clock.sleep,
    )
    bucket.acquire()
    bucket.penalize(factor=0.5, duration=10.0)
    bucket.penalize(factor=0.5, duration=20.0)  # extends window, same factor

    # Effective rate is still 1.0/s — gap is 1.0s, not 2.0s.
    bucket.acquire()
    assert clock.sleeps == [1.0]
