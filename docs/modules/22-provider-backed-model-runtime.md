# 模块 22：Provider 化模型运行时

## 目标

把模型调用从 agent 代码中剥离出来，让 agent 只依赖统一的 `ModelRuntime` 合约。v1a 默认仍使用 deterministic fake provider，但已经具备接入 OpenAI-compatible / Anthropic-compatible HTTP provider 的边界。

## 当前实现

- `Provider`
  - 最小协议：`complete(ModelRequest) -> dict`。
  - agent 不感知具体供应商。
- `FakeModelProvider`
  - 默认 provider。
  - 不需要 API key，不访问网络，适合单测、golden replay 和面试演示。
- `JsonPostTransport`
  - 标准库 JSON POST 传输层。
  - 独立出来后，provider 单测可以注入 fake transport。
- `HttpModelProvider`
  - OpenAI-compatible chat completions 形状。
  - 输入：`model/messages/temperature/response_format`。
  - 输出归一化为 `ok/content/usage`。
- `ConfiguredProviderFactory`
  - 从环境变量创建 provider。
  - 默认：`CIA_MODEL_PROVIDER=fake`。
  - 支持：
    - `CIA_MODEL_PROVIDER=openai-compatible`
    - `CIA_MODEL_PROVIDER=anthropic-compatible`
  - 非 fake provider 需要：
    - `CIA_MODEL_ENDPOINT`
    - `CIA_MODEL_API_KEY`
    - `CIA_MODEL_NAME`
- `ModelRuntime`
  - 捕获 provider 异常并返回 `ModelResponse(ok=False)`。
  - 当 `ModelRequest.response_format` 存在时，尝试解析 JSON 到 `ModelResponse.parsed`。

## 架构边界

模型供应商只存在于 runtime 层。Collector/Analyst/Writer/Reviewer 未来切到 LLM 生成时，也只拿 `ModelRequest/ModelResponse`，不会直接拼 HTTP、读取环境变量或处理供应商响应差异。

## 当前取舍

- `anthropic-compatible` 暂时复用 HTTP provider 边界，后续可替换为真正 Anthropic Messages API adapter。
- `ModelRuntime` 目前只做 best-effort JSON parse，不在 runtime 层绑定某个 agent schema。
- schema 校验放在模块 23 的 prompt/validator 层，保持职责单一。

## 测试

- `tests/unit/test_provider_model_runtime.py`
  - 默认 fake provider。
  - provider 抛错时返回结构化错误。
  - HTTP provider 归一化 OpenAI-compatible 响应。
  - provider factory 从环境变量创建 provider。
  - fake provider 仍为默认值。

## 完成标准

- agents 不依赖供应商 SDK 或环境变量。
- fake mode 仍然稳定。
- provider 错误不会直接 crash harness。
- usage 信息可以透传到 `ModelResponse`。
