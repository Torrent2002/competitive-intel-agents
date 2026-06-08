"""Model runtime — standardized model calls, provider-agnostic."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol
from urllib import request as urllib_request

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


class JsonPostTransport:
    """Standard-library JSON POST transport for HTTP model providers."""

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        timeout: float = 30.0,
    ) -> dict:
        data = json.dumps(payload).encode("utf-8")
        request = urllib_request.Request(
            url,
            data=data,
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                return json.loads(body)
        except Exception as exc:
            raise RuntimeError(f"model provider request failed: {exc}") from exc


class HttpModelProvider:
    """OpenAI-compatible chat completions provider."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        transport: JsonPostTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self._transport = transport or JsonPostTransport()
        self._timeout = timeout

    def complete(self, request: ModelRequest) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.response_format:
            payload["response_format"] = {"type": "json_object"}
        raw = self._transport.post_json(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            payload=payload,
            timeout=self._timeout,
        )
        content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {
            "ok": True,
            "content": content,
            "usage": raw.get("usage", {}),
        }


class ConfiguredProviderFactory:
    """Create providers from environment-like config."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        self._env = env if env is not None else os.environ

    def create(self) -> Provider:
        provider = self._env.get("CIA_MODEL_PROVIDER", "fake")
        if provider == "fake":
            return FakeModelProvider()
        if provider in {"openai-compatible", "anthropic-compatible"}:
            endpoint = self._env.get("CIA_MODEL_ENDPOINT", "")
            api_key = self._env.get("CIA_MODEL_API_KEY", "")
            model = self._env.get("CIA_MODEL_NAME", "")
            if not endpoint or not api_key or not model:
                raise ValueError(
                    "CIA_MODEL_ENDPOINT, CIA_MODEL_API_KEY, and CIA_MODEL_NAME are required"
                )
            return HttpModelProvider(endpoint=endpoint, api_key=api_key, model=model)
        raise ValueError(f"unsupported model provider: {provider}")


class ModelRuntime:
    """Normalize model calls through a provider, with optional structured parsing."""

    def __init__(self, provider: Provider | None = None) -> None:
        self._provider = provider or FakeModelProvider()

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
