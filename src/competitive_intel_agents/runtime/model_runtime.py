"""Model runtime — standardized model calls, provider-agnostic."""

from __future__ import annotations

import json
import os
import ssl
from urllib import error, request as urlrequest
from pathlib import Path
from typing import Any, Protocol

from competitive_intel_agents.models import ModelRequest, ModelResponse


def _build_ssl_context() -> ssl.SSLContext:
    """Build SSL context with certifi or system CA bundle."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for cert_path in (
        "/etc/ssl/cert.pem",
        "/etc/ssl/certs/ca-certificates.crt",
        "/opt/homebrew/etc/openssl@3/cert.pem",
        "/usr/local/etc/openssl@3/cert.pem",
    ):
        if Path(cert_path).exists():
            return ssl.create_default_context(cafile=cert_path)
    return ssl.create_default_context()


class Provider(Protocol):
    """Minimal provider contract for model completion."""

    def complete(self, request: ModelRequest) -> dict[str, Any]:
        """Return a dict with keys: ok, content, usage, and optionally error."""
        ...


class FakeModelProvider:
    """Deterministic fake model for tests — no API calls, no credentials.

    Returns structured JSON so downstream agents parse it, but every
    value is clearly marked [FAKE] to prevent silent misinterpretation.
    """

    @staticmethod
    def complete(request: ModelRequest) -> dict[str, Any]:
        import sys as _sys
        print(
            f"[model] WARNING: FakeModelProvider used for agent={request.agent} — "
            f"no real model configured",
            file=_sys.stderr,
        )
        agent = request.agent or "unknown"
        if agent == "analyst":
            content = '{"claims": [{"text": "[FAKE] No real model configured", "source_ids": [], "confidence": "low", "reasoning": "FakeModelProvider active"}]}'
        elif agent == "writer":
            content = '{"sections": {"Overview": "[FAKE] No real model configured", "Feature comparison": "", "Pricing": "", "SWOT": "", "Sources": ""}, "claim_ids": [], "source_ids": []}'
        elif agent == "reviewer":
            content = '{"feedback": [{"issue": "unsupported_claim", "target_agent": "writer", "target_artifact_id": "report", "message": "[FAKE] No real model configured — cannot verify report", "required_action": "Configure a real model in config/model.json", "severity": "blocking"}]}'
        elif agent == "collector":
            content = '{"sources": []}'
        else:
            content = f'{{"result": "[FAKE] No real model configured for {agent}"}}'
        return {
            "ok": True,
            "content": content,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "fake": True,
            },
        }


class JsonPostTransport:
    """JSON POST transport backed by the Python standard library."""

    def __init__(self) -> None:
        self._ssl_context = _build_ssl_context()

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        timeout: float = 30.0,
    ) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                **headers,
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=timeout, context=self._ssl_context) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.URLError, error.HTTPError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"model provider request failed: {exc}") from exc


class AnthropicMessagesProvider:
    """Anthropic Messages API provider (x-api-key auth, content blocks)."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        transport: JsonPostTransport | None = None,
        timeout: float = 180.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._transport = transport or JsonPostTransport()
        self._timeout = timeout

    def complete(self, request: ModelRequest) -> dict[str, Any]:
        system_parts: list[str] = []
        messages: list[dict[str, str]] = []
        for message in request.messages:
            role = message.get("role", "")
            content = message.get("content", "")
            if role == "system":
                system_parts.append(content)
                continue
            messages.append(message)
        # When the caller asked for JSON, defensively reinforce that in the
        # system prompt if no existing system part already mandates it.
        # Injecting an extra user message here would break the required
        # user/assistant alternation in the Anthropic Messages API, so we
        # add the instruction to the system block instead — this keeps the
        # provider safe for any future caller whose AgentPromptLibrary
        # system prompt does not happen to end in "Return ONLY valid JSON".
        if request.response_format == "json":
            joined_system = "\n\n".join(system_parts).lower()
            if "json" not in joined_system or "only" not in joined_system:
                system_parts.append(
                    "IMPORTANT: Respond with valid JSON only. "
                    "No markdown, no prose, no explanation outside the JSON object."
                )
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 32768,
            "messages": messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
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
    """Create model providers from env vars or a local JSON config.

    Loading order:
    1. Environment variables, for example `CIA_MODEL_PROVIDER` and
       `CIA_MODEL_API_KEY`.
    2. `config/model.json`, which is intentionally git-ignored because it may
       contain a real API key.

    To configure a local model without exporting env vars, copy
    `config/model.example.json` to `config/model.json` and fill:
    `provider`, `endpoint`, `api_key`, and `model`.
    """

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

    def _resolve_provider_config(self, overrides: dict | None = None) -> tuple[str, str, str, str]:
        """Resolve (provider, endpoint, api_key, model) with optional per-agent overrides."""
        provider = self._get("CIA_MODEL_PROVIDER") or self._get("provider") or "fake"
        endpoint = self._get("CIA_MODEL_ENDPOINT") or self._get("endpoint")
        api_key = self._get("CIA_MODEL_API_KEY") or self._get("api_key")
        model = self._get("CIA_MODEL_NAME") or self._get("model")
        if overrides:
            model = overrides.get("model", model)
        return provider, endpoint, api_key, model

    def _build_provider(self, provider: str, endpoint: str, api_key: str, model: str) -> Provider:
        if provider == "fake":
            return FakeModelProvider()
        if provider == "openai-compatible":
            if not endpoint or not api_key or not model:
                raise ValueError("Missing endpoint/api_key/model for openai-compatible provider")
            return HttpModelProvider(endpoint=endpoint, api_key=api_key, model=model)
        if provider == "anthropic-compatible":
            if not endpoint or not api_key or not model:
                raise ValueError("Missing endpoint/api_key/model for anthropic-compatible provider")
            return AnthropicMessagesProvider(endpoint=endpoint, api_key=api_key, model=model)
        raise ValueError(f"unsupported model provider: {provider}")

    def create(self) -> Provider:
        provider, endpoint, api_key, model = self._resolve_provider_config()
        return self._build_provider(provider, endpoint, api_key, model)

    def create_for_agent(self, agent_name: str) -> Provider:
        """Create a provider with per-agent model overrides from config.

        Config format: ``{"per_agent": {"writer": {"model": "..."}, ...}}``
        Falls back to default config if no override exists for *agent_name*.
        """
        cfg = self._load_config()
        per_agent = cfg.get("per_agent", {})
        overrides = per_agent.get(agent_name) if isinstance(per_agent, dict) else None
        provider, endpoint, api_key, model = self._resolve_provider_config(overrides)
        return self._build_provider(provider, endpoint, api_key, model)


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
