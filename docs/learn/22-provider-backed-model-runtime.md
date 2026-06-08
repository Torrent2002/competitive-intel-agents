# 学习文档 22：Provider 化模型运行时（已完成）

## 一句话概括

模块 22 让 agent 从"硬编码 if/else"变成"调 LLM API"。支持 OpenAI 和 Anthropic 两种 API 格式，通过 `config/model.json` 或环境变量配置，fake 模式保持不变。

## 为什么需要它

v0 的 agent 是硬编码的：collector 用模板拼 query，analyst 用固定句子写 claim，writer 用固定模板填 section。模块 22+23 是让 agent 真正"动脑子"的关键。

## 关键代码

- `src/competitive_intel_agents/runtime/model_runtime.py`
  - `HttpModelProvider`：OpenAI 格式（`Authorization: Bearer`，响应从 `choices[0].message.content` 提取）
  - `AnthropicMessagesProvider`：Anthropic 格式（`x-api-key`，`anthropic-version`，响应从 `content[].text` 提取）
  - `ConfiguredProviderFactory`：环境变量优先 → `config/model.json` 兜底。明确传 `env={}` 时不读配置文件（给测试用）
  - `JsonPostTransport`：自动检测 macOS Homebrew Python SSL 证书路径

### 配置方式

`config/model.json`（已加入 `.gitignore`）：
```json
{
  "provider": "anthropic-compatible",
  "endpoint": "https://api.deepseek.com/anthropic",
  "model": "deepseek-v4-flash"
}
```

API key 通过环境变量 `CIA_MODEL_API_KEY` 传入，避免写入文件。

### Anthropic vs OpenAI API 的关键差异

| | OpenAI | Anthropic |
|---|---|---|
| 端点 | `/v1/chat/completions` | `/v1/messages` |
| 认证 | `Authorization: Bearer` | `x-api-key` |
| 响应格式 | `choices[0].message.content` | `content[0].text` |
| response_format | 原生支持 `json_object` | 不支持，需 prompt 注入 |

### JSON 解析的三层兜底

```python
# 1. 直接 json.loads
try: return json.loads(content)
# 2. 提取 ```json ... ```
m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content)
# 3. 正则匹配 { ... }
m = re.search(r'\{.*\}', content)
```

### SSL 证书自动修复

macOS Homebrew Python 缺少根证书，代码自动检测：
```python
for cert_path in ("/etc/ssl/cert.pem", "/opt/homebrew/etc/openssl@3/cert.pem"):
    if Path(cert_path).exists():
        os.environ["SSL_CERT_FILE"] = cert_path
```

## 面试怎么讲

> 模型运行时是 agent 和 LLM 之间的抽象层。agent 不直接拼 HTTP，不解析供应商响应差异。我们同时支持 OpenAI 和 Anthropic 两种 API 格式，fake 模式对 186 个单元测试完全透明——不配置 API key 就回退到确定性 fake provider。SSL 证书在 macOS Homebrew Python 下自动修复，用户不需要手动配置。
