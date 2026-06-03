# 07 Model Runtime

## Goal

Standardize model calls so agents do not depend directly on a specific provider SDK.

## Scope

In scope:

- Provider interface.
- Fake deterministic model for tests.
- Prompt/message envelope.
- Structured output parsing hook.
- Usage and error normalization.

Out of scope:

- Prompt optimization.
- Provider-specific advanced features.
- Streaming responses.

## Public Interface

```python
class ModelRuntime:
    def complete(self, request: ModelRequest) -> ModelResponse: ...
```

## Providers v0

- `FakeModelProvider` for deterministic tests.
- `ClaudeModelProvider` placeholder.
- `OpenAICompatibleProvider` placeholder.

The real providers can be thin adapters. The fake provider is required before real API integration so module tests do not depend on network or credentials.

## Tests

- Fake model returns deterministic content.
- Provider errors become `ModelResponse(ok=False, error=...)`.
- Usage counters are preserved when available.
- Structured output parsing failures are reported without crashing the harness.

## Done Criteria

- Agents can request model output through `ModelRuntime`.
- Unit tests run without real API keys.
- Runtime and harness can handle normalized model errors.

