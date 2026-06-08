# 模块 22：Provider 化模型运行时（已完成）

## 目标

把模型调用从 agent 代码中剥离出来，让 agent 只依赖统一的 `ModelRuntime` 合约。默认使用 deterministic fake provider，支持接入 OpenAI-compatible / Anthropic-compatible HTTP provider。通过 `config/model.json` 或环境变量配置。

## 当前实现

- `Provider`
  - 最小协议：`complete(ModelRequest) -> dict`。
  - agent 不感知具体供应商。
- `FakeModelProvider`
  - 默认 provider，不需要 API key，不访问网络。
- `JsonPostTransport`
  - 标准库 JSON POST 传输层，自动检测 macOS Homebrew Python SSL 证书。
- `HttpModelProvider`
  - OpenAI-compatible 格式：`Authorization: Bearer`，响应从 `choices[0].message.content` 提取。
- `AnthropicMessagesProvider`（新增）
  - Anthropic Messages API 格式：`x-api-key` 头，`anthropic-version: 2023-06-01`。
  - 请求：`{model, max_tokens, messages}`。
  - 响应从 `content[].text` 提取。
  - 当 `response_format` 要求 JSON 时，注入 JSON 指令到末尾消息（Anthropic API 不原生支持 `response_format`）。
- `ConfiguredProviderFactory`
  - 读取顺序：环境变量优先 → `config/model.json` 兜底。
  - 支持 provider 类型：
    - `openai-compatible` → `HttpModelProvider`
    - `anthropic-compatible` → `AnthropicMessagesProvider`
    - `fake`（默认）
  - `config/model.json` 配置示例：
    ```json
    {
      "provider": "anthropic-compatible",
      "endpoint": "https://api.deepseek.com/anthropic",
      "api_key": "",
      "model": "deepseek-v4-flash"
    }
    ```
  - API key 可通过 `CIA_MODEL_API_KEY` 环境变量覆盖（避免写入文件）。
- `ModelRuntime`
  - 捕获 provider 异常并返回 `ModelResponse(ok=False)`。
  - JSON 解析：直接 `json.loads` → markdown code block 提取 → 裸 `{...}` 正则匹配。

## 架构边界

模型供应商只存在于 runtime 层。Agent 只拿 `ModelRequest/ModelResponse`，不直接拼 HTTP、读环境变量。

## 当前取舍

- `config/model.json` 已加入 `.gitignore`，API key 推荐用环境变量。
- SSL 证书自动检测 macOS 路径：`/etc/ssl/cert.pem`、`/opt/homebrew/etc/openssl@3/cert.pem`。

## 测试

- `tests/unit/test_provider_model_runtime.py`
  - 默认 fake provider。
  - provider 抛错时返回结构化错误。
  - HTTP provider 归一化 OpenAI-compatible 和 Anthropic 响应。
  - 明确传入 `env={}` 时不读取配置文件。

## 完成标准

- [x] agents 不依赖供应商 SDK 或环境变量。
- [x] fake mode 仍然稳定。
- [x] provider 错误不会直接 crash harness。
- [x] usage 信息透传到 `ModelResponse`。
- [x] 支持 Anthropic Messages API（DeepSeek 等兼容端点）。
- [x] `config/model.json` 配置文件，无需每次 export 环境变量。
- [x] Agent 已通过 `--real-model` 接入模型运行时（collector/analyst/writer/reviewer）。
