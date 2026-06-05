# 07 Model Runtime — 面试级学习笔记

## 一句话概括

**Model Runtime 是 agent 和大模型之间的 provider-agnostic 适配层，让你可以在 fake / Claude / OpenAI 之间切换，agent 代码一行不用改。**

---

## 1. 为什么需要这一层？

直接让 agent 调 `anthropic.Anthropic().messages.create()` 的问题：

| 问题 | 后果 |
|---|---|
| 单测依赖网络和 API key | CI 跑不了，开发速度慢 |
| Agent 和 provider 强耦合 | 换模型要改所有 agent 代码 |
| 错误处理不一致 | Claude 抛异常，OpenAI 抛另一种异常，Harness 没法统一处理 |
| 无法模拟模型行为 | 没法测试"模型返回了不合法 JSON"时 agent 的行为 |

---

## 2. 两个核心设计

### 2.1 Provider Protocol — 极简契约

```python
class Provider(Protocol):
    def complete(self, request: ModelRequest) -> dict[str, Any]: ...
```

Provider 只需要一个 `complete` 方法，返回一个**普通 dict**（不是 ModelResponse）。为什么是 dict？

- **解耦** — Provider 不需要 import `ModelResponse`，可以是完全独立的包
- **错误收敛** — `ModelRuntime.complete()` 统一把 dict 转成 `ModelResponse`，集中处理 parsing 和异常

### 2.2 ModelRuntime 作为错误边界

```python
class ModelRuntime:
    def complete(self, request: ModelRequest) -> ModelResponse:
        try:
            raw = self._provider.complete(request)   # ① 捕获异常
        except Exception as exc:
            return ModelResponse(ok=False, error=str(exc))

        # ② 结构化解析 — best-effort，失败不 crash
        parsed = None
        if ok and request.response_format and content:
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                pass

        return ModelResponse(ok=ok, content=content, parsed=parsed, ...)
```

三层保护：
1. **Provider 异常** → `ModelResponse(ok=False, error=...)`
2. **JSON 解析失败** → `parsed=None`，但 `ok=True`（模型确实返回了内容，只是不合法 JSON）
3. **Harness 永远拿到的都是 ModelResponse** — 不需要 try/except

---

## 3. FakeModelProvider — 测试的基础设施

```python
class FakeModelProvider:
    @staticmethod
    def complete(request: ModelRequest) -> dict[str, Any]:
        messages_text = " ".join(m.get("content", "") for m in request.messages)
        content = (
            f"[Fake {request.agent} response] "
            f'Based on the input: "{messages_text}". '
        )
        return {
            "ok": True,
            "content": content,
            "usage": {"input_tokens": ..., "output_tokens": ...},
        }
```

关键属性：
- **确定性** — 相同输入永远相同输出（测试可重复）
- **输入感知** — 输出包含 agent 名和 message 内容，方便验证"agent 传了正确的 context"
- **Usage 模拟** — 返回合成的 token 计数，让 budget 检查逻辑可测试

---

## 4. 面试常见追问

**Q: 为什么 Provider 返回 dict 而不是 ModelResponse？**

A: 让 Provider 实现对 `competitive_intel_agents` 零依赖。一个外部团队可以写一个 `MyProvider.complete() -> dict`，不需要安装我们的包。`ModelRuntime` 负责 dict → ModelResponse 的转换。

**Q: `response_format` 是干嘛的？为什么不直接用 function calling？**

A: v0 阶段用简单的 JSON 文本解析 (`json.loads(content)`) 模拟结构化输出。真实 provider 可以用 native structured output（如 Claude 的 `tool_use`），但对 test 来说，文本里塞 JSON 就够了。

**Q: 真实 provider 的 placeholder 怎么实现？**

A: 以 Claude 为例：
```python
class ClaudeModelProvider:
    def __init__(self, api_key: str):
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, request: ModelRequest) -> dict:
        resp = self._client.messages.create(
            model="claude-sonnet-4-6",
            messages=request.messages,
        )
        return {
            "ok": True,
            "content": resp.content[0].text,
            "usage": {"input_tokens": resp.usage.input_tokens, ...},
        }
```
替换 `ModelRuntime(provider=ClaudeModelProvider(key))` 即可，agent 和 harness 不动。

**Q: `ModelRuntime.complete` 为什么不直接调 API 要加一个 Provider 层？**

A: 这是 Strategy 模式。Provider 是可变策略，ModelRuntime 是稳定上下文。单测用 Fake，生产用 Claude，性能测试用 OpenAI Compatible，切换策略不需要改 ModelRuntime。

---

## 5. 和前后模块的关系

| 依赖 | 关系 |
|---|---|
| ← 02 Core Models | `ModelRequest`, `ModelResponse` |
| → 08 Runtime Harness | Harness 持有 `ModelRuntime` 实例，每轮 agent 调 `model_runtime.complete()` |
| → 09-12 Agents | Agent 通过 Harness 间接使用 ModelRuntime，不直接持有引用 |

---

## 6. 测试覆盖

```
test_fake_model_returns_deterministic_content  # 确定性输出
test_fake_model_content_varies_by_agent        # 不同 agent → 不同输出
test_fake_model_includes_user_message_context  # 输出反映输入
test_fake_model_reports_usage_counters         # 合成 token 计数
test_provider_errors_become_failed_response    # 异常 → ok=False
test_structured_output_parsing_success         # JSON 解析成功
test_structured_output_parsing_failure         # 解析失败不 crash
test_custom_provider_matches_protocol          # 任意 Provider 兼容
```
