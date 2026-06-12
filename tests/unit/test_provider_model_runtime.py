from competitive_intel_agents.models import ModelRequest
from competitive_intel_agents.runtime import (
    AnthropicMessagesProvider,
    ConfiguredProviderFactory,
    FakeModelProvider,
    HttpModelProvider,
    ModelRuntime,
)


def test_model_runtime_defaults_to_fake_provider() -> None:
    runtime = ModelRuntime()

    response = runtime.complete(
        ModelRequest(agent="analyst", messages=[{"role": "user", "content": "hello"}])
    )

    assert response.ok is True
    assert "[Fake analyst response]" in response.content


def test_model_runtime_returns_error_when_provider_raises() -> None:
    class BrokenProvider:
        def complete(self, request):
            raise RuntimeError("provider down")

    response = ModelRuntime(provider=BrokenProvider()).complete(
        ModelRequest(agent="writer", messages=[])
    )

    assert response.ok is False
    assert response.error == "provider down"


def test_http_model_provider_normalizes_openai_compatible_response() -> None:
    class Transport:
        def post_json(self, url, headers, payload, timeout):
            return {
                "choices": [{"message": {"content": "{\"ok\": true}"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            }

    provider = HttpModelProvider(
        endpoint="https://api.example.com/v1/chat/completions",
        api_key="secret",
        model="test-model",
        transport=Transport(),
    )

    raw = provider.complete(
        ModelRequest(
            agent="reviewer",
            messages=[{"role": "user", "content": "review"}],
            response_format="json",
        )
    )

    assert raw["ok"] is True
    assert raw["content"] == "{\"ok\": true}"
    assert raw["usage"] == {"prompt_tokens": 3, "completion_tokens": 2}


def test_anthropic_provider_moves_system_message_to_top_level_payload() -> None:
    class Transport:
        def __init__(self) -> None:
            self.payload = None

        def post_json(self, url, headers, payload, timeout):
            self.payload = payload
            return {
                "content": [{"type": "text", "text": "{\"ok\": true}"}],
                "usage": {"input_tokens": 3, "output_tokens": 2},
            }

    transport = Transport()
    provider = AnthropicMessagesProvider(
        endpoint="https://api.example.com",
        api_key="secret",
        model="test-model",
        transport=transport,
    )

    provider.complete(
        ModelRequest(
            agent="analyst",
            messages=[
                {"role": "system", "content": "System instructions."},
                {"role": "user", "content": "Analyze ACME."},
            ],
            response_format="json",
        )
    )

    # When the system prompt does not already mandate JSON-only output,
    # the provider defensively appends a JSON instruction to the system
    # block (rather than as a user message, which would break the
    # required user/assistant alternation in the Anthropic API).
    assert transport.payload["system"].startswith("System instructions.")
    assert "JSON" in transport.payload["system"]
    # response_format="json" no longer injects an extra user message —
    # JSON enforcement lives in the system block to keep user/assistant
    # alternation valid.
    assert [message["role"] for message in transport.payload["messages"]] == [
        "user",
    ]


def test_anthropic_provider_does_not_duplicate_json_instruction_when_already_present() -> None:
    class Transport:
        def __init__(self) -> None:
            self.payload = None

        def post_json(self, url, headers, payload, timeout):
            self.payload = payload
            return {
                "content": [{"type": "text", "text": "{\"ok\": true}"}],
                "usage": {"input_tokens": 3, "output_tokens": 2},
            }

    transport = Transport()
    provider = AnthropicMessagesProvider(
        endpoint="https://api.example.com",
        api_key="secret",
        model="test-model",
        transport=transport,
    )

    provider.complete(
        ModelRequest(
            agent="analyst",
            messages=[
                {
                    "role": "system",
                    "content": "Return ONLY valid JSON. No markdown.",
                },
                {"role": "user", "content": "Analyze ACME."},
            ],
            response_format="json",
        )
    )

    # System prompt already mandates JSON-only output — provider should
    # leave it untouched rather than tack on a redundant reminder.
    assert transport.payload["system"] == "Return ONLY valid JSON. No markdown."


def test_configured_provider_factory_uses_env_without_leaking_into_agents() -> None:
    env = {
        "CIA_MODEL_PROVIDER": "openai-compatible",
        "CIA_MODEL_ENDPOINT": "https://api.example.com/v1/chat/completions",
        "CIA_MODEL_API_KEY": "secret",
        "CIA_MODEL_NAME": "test-model",
    }

    provider = ConfiguredProviderFactory(env=env).create()

    assert isinstance(provider, HttpModelProvider)


def test_configured_provider_factory_keeps_fake_as_default() -> None:
    provider = ConfiguredProviderFactory(env={}).create()

    assert isinstance(provider, FakeModelProvider)
