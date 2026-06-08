# 学习文档 22：Provider 化模型运行时

## 这个模块解决什么

项目未来要接真实 LLM，但 agent 不应该直接依赖 OpenAI、Anthropic 或其他厂商 SDK。模块 22 把模型调用收敛到 `ModelRuntime`，让 provider 成为可替换的 runtime 插件。

## 关键代码

- `src/competitive_intel_agents/runtime/model_runtime.py`
  - `Provider`：模型供应商最小协议。
  - `FakeModelProvider`：默认 fake provider。
  - `JsonPostTransport`：HTTP JSON POST 传输层。
  - `HttpModelProvider`：OpenAI-compatible chat completions 适配器。
  - `ConfiguredProviderFactory`：从环境变量创建 provider。
  - `ModelRuntime`：统一返回 `ModelResponse`。

## 环境变量

默认不需要任何环境变量，会使用 fake provider。

接真实 provider 时：

```bash
export CIA_MODEL_PROVIDER=openai-compatible
export CIA_MODEL_ENDPOINT=https://api.example.com/v1/chat/completions
export CIA_MODEL_API_KEY=your_api_key
export CIA_MODEL_NAME=your_model_name
```

当前 `anthropic-compatible` 先作为边界占位，后续可以替换成真正 Anthropic Messages adapter。

## 为什么这样设计

模型供应商变化很快，如果 agent 直接拼 HTTP 请求，后续会出现三类问题：

1. 单测需要真实 key 或复杂 mock。
2. 每个 agent 都要处理 provider 差异。
3. provider 异常可能直接打断 harness。

现在 `ModelRuntime.complete()` 会把异常转成 `ModelResponse(ok=False)`，provider response 也归一化到 `content/usage/parsed/error`。这让 agent 代码只关注业务结构。

## 后续扩展

- 真正实现 Anthropic Messages API adapter。
- 将 usage 写入 journal 或 dashboard。
- 增加 provider retry/backoff。
- 支持按 agent profile 选择模型。
