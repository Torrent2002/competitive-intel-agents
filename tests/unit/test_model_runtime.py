"""Tests for the Model Runtime (Module 07)."""

import json

import pytest

from competitive_intel_agents.models import ModelRequest
from competitive_intel_agents.runtime.model_runtime import (
    FakeModelProvider,
    ModelRuntime,
    Provider,
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
