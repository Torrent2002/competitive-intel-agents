"""Tests for the Model Runtime (Module 07)."""

import json
from unittest import mock
from urllib import error

import pytest

from competitive_intel_agents.models import ModelRequest
from competitive_intel_agents.runtime.model_runtime import (
    FakeModelProvider,
    JsonPostTransport,
    ModelRuntime,
    NonRetryableProviderError,
    Provider,
    RetryableProviderError,
)


def make_request(
    agent: str = "analyst",
    messages: list | None = None,
    response_format: str | None = None,
) -> ModelRequest:
    return ModelRequest(
        agent=agent,
        messages=messages or [{"role": "user", "content": "Analyze the market"}],
        response_format=response_format,
        temperature=0.0,
    )


# ── Fake provider ───────────────────────────────────────────────

def test_fake_model_returns_deterministic_content() -> None:
    """Fake provider must return the same output for the same input."""
    runtime = ModelRuntime(provider=FakeModelProvider())
    request = make_request()

    response_a = runtime.complete(request)
    response_b = runtime.complete(request)

    assert response_a.ok is True
    assert response_a.content == response_b.content


def test_fake_model_content_varies_by_agent() -> None:
    """Different agents should get different content from the fake provider."""
    runtime = ModelRuntime(provider=FakeModelProvider())

    collector_resp = runtime.complete(make_request(agent="collector"))
    analyst_resp = runtime.complete(make_request(agent="analyst"))

    assert collector_resp.content != analyst_resp.content
    assert "sources" in collector_resp.content.lower()
    assert "claims" in analyst_resp.content.lower()


def test_fake_model_includes_user_message_context() -> None:
    """Fake provider output should be structured JSON, not reflecting input content."""
    runtime = ModelRuntime(provider=FakeModelProvider())
    request = make_request(
        messages=[{"role": "user", "content": "ACME competitive analysis"}]
    )

    response = runtime.complete(request)

    assert response.ok is True
    assert response.content  # returns valid JSON content
    assert "[FAKE]" in response.content


# ── Usage counters ──────────────────────────────────────────────

def test_fake_model_reports_usage_counters() -> None:
    """Fake provider should report usage stats with fake flag."""
    runtime = ModelRuntime(provider=FakeModelProvider())

    response = runtime.complete(make_request())

    assert response.usage  # usage dict should not be empty
    assert "input_tokens" in response.usage
    assert "output_tokens" in response.usage
    assert response.usage.get("fake") is True


# ── Error handling ──────────────────────────────────────────────

def test_provider_errors_become_failed_response() -> None:
    """When a provider raises, ModelRuntime must return ok=False, not crash."""

    class FailingProvider:
        def complete(self, request: ModelRequest):
            raise RuntimeError("API key invalid")

    runtime = ModelRuntime(provider=FailingProvider())
    response = runtime.complete(make_request())

    assert response.ok is False
    assert response.error is not None
    assert "API key invalid" in response.error


# ── Structured output parsing ───────────────────────────────────

def test_structured_output_parsing_success() -> None:
    """When response_format is set, parsed field should contain the parsed JSON."""

    class JsonProvider:
        def complete(self, request: ModelRequest):
            return {
                "ok": True,
                "content": '{"claims": [{"text": "Market grows 15%", "confidence": "high"}]}',
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }

    runtime = ModelRuntime(provider=JsonProvider())
    request = make_request(response_format="claims_json")

    response = runtime.complete(request)

    assert response.ok is True
    assert response.parsed is not None
    assert response.parsed["claims"][0]["text"] == "Market grows 15%"


def test_structured_output_parsing_failure_is_not_crash() -> None:
    """If parsing fails, the response should still be ok=True but parsed=None."""

    class BadJsonProvider:
        def complete(self, request: ModelRequest):
            return {
                "ok": True,
                "content": "not valid json {{{",
                "usage": {"input_tokens": 5, "output_tokens": 3},
            }

    runtime = ModelRuntime(provider=BadJsonProvider())
    request = make_request(response_format="claims_json")

    response = runtime.complete(request)

    # Response itself should be ok — the model did return a response
    assert response.ok is True
    # But parsed is None because the JSON was invalid
    assert response.parsed is None
    # content should still be preserved
    assert response.content == "not valid json {{{"


# ── Provider protocol ───────────────────────────────────────────

def test_custom_provider_matches_protocol() -> None:
    """Any object with a complete() method should work as a provider."""

    class CustomProvider:
        def complete(self, request: ModelRequest):
            return {
                "ok": True,
                "content": "custom output",
                "usage": {},
            }

    runtime = ModelRuntime(provider=CustomProvider())
    response = runtime.complete(make_request())

    assert response.ok is True
    assert response.content == "custom output"


# ── Retry behavior (Module 32) ──────────────────────────────────


class _ScriptedProvider:
    """Provider that yields a sequence of outcomes (exception or dict)."""

    def __init__(self, outcomes: list) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def complete(self, request: ModelRequest):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_model_runtime_retries_on_retryable_error_then_succeeds() -> None:
    """Retryable provider errors should retry up to max_retries before succeeding."""

    sleeps: list[float] = []
    provider = _ScriptedProvider(
        [
            RetryableProviderError("HTTP 429 Too Many Requests"),
            RetryableProviderError("HTTP 503 Service Unavailable"),
            {"ok": True, "content": "third time lucky", "usage": {}},
        ]
    )
    runtime = ModelRuntime(
        provider=provider,
        max_retries=3,
        backoff_base=1.0,
        sleep=sleeps.append,
    )

    response = runtime.complete(make_request())

    assert response.ok is True
    assert response.content == "third time lucky"
    assert provider.calls == 3
    # Backoff between attempts: 1s after first failure, 2s after second.
    assert sleeps == [1.0, 2.0]


def test_model_runtime_does_not_retry_on_non_retryable() -> None:
    """4xx-class errors must fail immediately — retrying just burns budget."""

    sleeps: list[float] = []
    provider = _ScriptedProvider(
        [NonRetryableProviderError("HTTP 401 Unauthorized")]
    )
    runtime = ModelRuntime(
        provider=provider,
        max_retries=3,
        sleep=sleeps.append,
    )

    response = runtime.complete(make_request())

    assert response.ok is False
    assert response.error is not None
    assert "401" in response.error
    assert provider.calls == 1
    assert sleeps == []


def test_model_runtime_returns_failed_after_exhausting_retries() -> None:
    """When every attempt is retryable, the runtime gives up after max_retries."""

    sleeps: list[float] = []
    provider = _ScriptedProvider(
        [
            RetryableProviderError("attempt 1 boom"),
            RetryableProviderError("attempt 2 boom"),
            RetryableProviderError("attempt 3 boom"),
            RetryableProviderError("attempt 4 boom"),
        ]
    )
    runtime = ModelRuntime(
        provider=provider,
        max_retries=3,
        backoff_base=1.0,
        backoff_max=8.0,
        sleep=sleeps.append,
    )

    response = runtime.complete(make_request())

    assert response.ok is False
    assert response.error is not None
    assert "attempt 4 boom" in response.error
    # 1 initial attempt + 3 retries = 4 total calls
    assert provider.calls == 4
    # Backoff: 1s, 2s, 4s (each capped by backoff_max=8)
    assert sleeps == [1.0, 2.0, 4.0]


def test_json_post_transport_classifies_429_as_retryable() -> None:
    """JsonPostTransport should map HTTP 429 to RetryableProviderError."""

    transport = JsonPostTransport()
    fake_error = error.HTTPError(
        "https://example.com/v1",
        429,
        "Too Many Requests",
        hdrs=None,
        fp=None,
    )

    with mock.patch(
        "competitive_intel_agents.runtime.model_runtime.urlrequest.urlopen",
        side_effect=fake_error,
    ):
        with pytest.raises(RetryableProviderError) as excinfo:
            transport.post_json(
                "https://example.com/v1",
                headers={},
                payload={"q": "ping"},
                timeout=1.0,
            )

    assert "429" in str(excinfo.value)


def test_json_post_transport_classifies_400_as_non_retryable() -> None:
    """JsonPostTransport should map HTTP 400 to NonRetryableProviderError."""

    transport = JsonPostTransport()
    fake_error = error.HTTPError(
        "https://example.com/v1",
        400,
        "Bad Request",
        hdrs=None,
        fp=None,
    )

    with mock.patch(
        "competitive_intel_agents.runtime.model_runtime.urlrequest.urlopen",
        side_effect=fake_error,
    ):
        with pytest.raises(NonRetryableProviderError) as excinfo:
            transport.post_json(
                "https://example.com/v1",
                headers={},
                payload={"q": "ping"},
                timeout=1.0,
            )

    assert "400" in str(excinfo.value)
