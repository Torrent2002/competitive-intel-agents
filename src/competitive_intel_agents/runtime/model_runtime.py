"""Model runtime — standardized model calls, provider-agnostic."""

from __future__ import annotations

import json
from typing import Any, Protocol

from competitive_intel_agents.models import ModelRequest, ModelResponse


class Provider(Protocol):
    """Minimal provider contract for model completion."""

    def complete(self, request: ModelRequest) -> dict[str, Any]:
        """Return a dict with keys: ok, content, usage, and optionally error."""
        ...


class FakeModelProvider:
    """Deterministic fake model for tests — no API calls, no credentials."""

    @staticmethod
    def complete(request: ModelRequest) -> dict[str, Any]:
        messages_text = " ".join(
            m.get("content", "") for m in request.messages if m.get("content")
        )
        content = (
            f"[Fake {request.agent} response] "
            f"Based on the input: \"{messages_text}\". "
            f"This is deterministic fake output for testing."
        )
        return {
            "ok": True,
            "content": content,
            "usage": {
                "input_tokens": max(10, len(messages_text) // 4),
                "output_tokens": max(5, len(content) // 4),
            },
        }


class ModelRuntime:
    """Normalize model calls through a provider, with optional structured parsing."""

    def __init__(self, provider: Provider) -> None:
        self._provider = provider

    def complete(self, request: ModelRequest) -> ModelResponse:
        # Call the provider — catch any exception so the harness never crashes
        try:
            raw = self._provider.complete(request)
        except Exception as exc:
            return ModelResponse(
                ok=False,
                error=str(exc),
            )

        ok = raw.get("ok", False)
        content = raw.get("content", "")
        usage = raw.get("usage", {})
        error = raw.get("error")

        # Structured output parsing — best-effort, never crashes
        parsed = None
        if ok and request.response_format and content:
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                pass  # parsing failure is non-fatal

        return ModelResponse(
            ok=ok,
            content=content,
            parsed=parsed,
            usage=usage,
            error=error,
        )
