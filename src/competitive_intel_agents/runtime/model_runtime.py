"""Model runtime — standardized model calls, provider-agnostic."""

from __future__ import annotations

import json
import os
from pathlib import Path
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


def _ensure_ssl_certs() -> None:
    """Auto-detect SSL cert file for Homebrew Python on macOS."""
    if os.environ.get("SSL_CERT_FILE"):
        return  # already configured
    for cert_path in (
        "/etc/ssl/cert.pem",
        "/opt/homebrew/etc/openssl@3/cert.pem",
        "/usr/local/etc/openssl@3/cert.pem",
    ):
        if Path(cert_path).exists():
            os.environ["SSL_CERT_FILE"] = cert_path
            return


class JsonPostTransport:
    """Standard-library JSON POST transport for HTTP model providers."""

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        timeout: float = 30.0,
    ) -> dict:
        _ensure_ssl_certs()
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


class AnthropicMessagesProvider:
    """Anthropic Messages API provider (x-api-key auth, content blocks)."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        transport: JsonPostTransport | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._transport = transport or JsonPostTransport()
        self._timeout = timeout

    def complete(self, request: ModelRequest) -> dict[str, Any]:
        messages = list(request.messages)
        if request.response_format:
            # Anthropic API doesn't support response_format — inject JSON instruction
            messages.append({
                "role": "user",
                "content": "IMPORTANT: You MUST respond with valid JSON only. No markdown, no explanation."
            })
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 2048,
            "messages": messages,
        }
        raw = self._transport.post_json(
            f"{self.endpoint}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            payload=payload,
            timeout=self._timeout,
        )
        # Anthropic response: content is an array of blocks
        content_blocks = raw.get("content", [])
        content = ""
        if isinstance(content_blocks, list):
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    content += block.get("text", "")
        return {
            "ok": True,
            "content": content,
            "usage": raw.get("usage", {}),
        }


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
    """Create providers from env vars, falling back to config/model.json."""

    _DEFAULT_PATHS = (Path(__file__).resolve().parents[3] / "config" / "model.json",)

    def __init__(
        self,
        env: dict[str, str] | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        self._env = env if env is not None else os.environ
        self._explicit_env = env is not None  # if True, don't fall back to config file
        self._config_path = Path(config_path) if config_path else None
        self._config: dict[str, object] | None = None

    def _load_config(self) -> dict[str, object]:
        if self._config is not None:
            return self._config
        if self._explicit_env:
            self._config = {}
            return self._config
        paths = [self._config_path] if self._config_path else list(self._DEFAULT_PATHS)
        for p in paths:
            if p and p.exists():
                try:
                    self._config = json.loads(p.read_text(encoding="utf-8"))
                    return self._config
                except (json.JSONDecodeError, OSError):
                    pass
        self._config = {}
        return self._config

    def _get(self, key: str, default: str = "") -> str:
        """Env var takes priority, then config file, then default."""
        env_val = self._env.get(key, "")
        if env_val:
            return env_val
        cfg = self._load_config()
        cfg_val = cfg.get(key)
        if isinstance(cfg_val, str) and cfg_val:
            return cfg_val
        return default

    def create(self) -> Provider:
        provider = self._get("CIA_MODEL_PROVIDER") or self._get("provider") or "fake"
        if provider == "fake":
            return FakeModelProvider()
        if provider == "openai-compatible":
            endpoint = self._get("CIA_MODEL_ENDPOINT") or self._get("endpoint")
            api_key = self._get("CIA_MODEL_API_KEY") or self._get("api_key")
            model = self._get("CIA_MODEL_NAME") or self._get("model")
            if not endpoint or not api_key or not model:
                raise ValueError(
                    "Set CIA_MODEL_ENDPOINT/api_key/name env vars or configure config/model.json"
                )
            return HttpModelProvider(endpoint=endpoint, api_key=api_key, model=model)
        if provider == "anthropic-compatible":
            endpoint = self._get("CIA_MODEL_ENDPOINT") or self._get("endpoint")
            api_key = self._get("CIA_MODEL_API_KEY") or self._get("api_key")
            model = self._get("CIA_MODEL_NAME") or self._get("model")
            if not endpoint or not api_key or not model:
                raise ValueError(
                    "Set CIA_MODEL_ENDPOINT/api_key/name env vars or configure config/model.json"
                )
            return AnthropicMessagesProvider(
                endpoint=endpoint, api_key=api_key, model=model
            )
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
                # Try extracting JSON from markdown code blocks
                import re as _re
                m = _re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, _re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(1))
                    except (json.JSONDecodeError, TypeError):
                        pass
                if parsed is None:
                    # Try finding JSON object in text
                    m = _re.search(r'\{.*\}', content, _re.DOTALL)
                    if m:
                        try:
                            parsed = json.loads(m.group(0))
                        except (json.JSONDecodeError, TypeError):
                            pass

        return ModelResponse(
            ok=ok,
            content=content,
            parsed=parsed,
            usage=usage,
            error=error,
        )
