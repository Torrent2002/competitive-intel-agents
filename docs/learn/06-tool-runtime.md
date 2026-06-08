# 06 Tool Runtime — 面试级学习笔记

## 一句话概括

**Tool Runtime 是 agent 和外部工具之间的标准化中间层，负责权限校验、调用执行、签名生成三条职责。**

---

## 1. 为什么需要这一层？

如果每个 agent 直接调 `requests.get(url)` 或 `google_search(query)`，会导致：

- **权限失控** — Analyst 也能搜网页，但它不应该有网络权限
- **测试不可控** — 单测依赖真实网络和 API key
- **重复调用无法检测** — Harness 不知道两次 `web_search("ACME")` 是不是同一件事
- **Agent 和工具实现耦合** — 换一个搜索后端要改所有 agent 代码

Tool Runtime 用一个中心化的 `execute(agent, call) → ToolResult` 消除这些耦合。

---

## 2. 三层架构

```
Agent                       ToolRuntime                  Tool
─────                       ───────────                  ────
collector.run_round()  ──→  execute("collector", call)
                              │
                              ├─ 1. ToolPolicy.ensure_allowed()
                              │      ├─ requested_by 必须匹配当前 agent
                              │      └─ role ceiling ∩ run profile
                              ├─ 2. lookup tool by name
                              └─ 3. tool.run(args)     ──→  FakeWebSearch.run()
                                                            │
                              ←── ToolResult(ok, data)  ←──  {"results": [...]}
```

---

## 3. 核心设计决策

### 3.1 为什么用 Protocol 而不是 ABC？

```python
class Tool(Protocol):
    name: str
    def run(self, args: dict) -> dict: ...
```

Tool 没有共享状态、不需要 `__init__`、没有子类关系。Protocol 满足"只要能 run 就是 Tool"的鸭子类型，比 ABC 更轻。`FakeWebSearch` 甚至不需要显式继承它。

### 3.2 签名为什么用 SHA-256？

```python
def signature(self, call: ToolCall) -> str:
    payload = json.dumps({"name": call.name, "args": call.args}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()
```

三个保证：
- **确定性** — 相同 name + args → 相同签名
- **无关性** — 忽略 `call.id` 和 `call.requested_by`，只关注"做了什么"
- **稳定排序** — `sort_keys=True` 避免 `{"a":1,"b":2}` 和 `{"b":2,"a":1}` 产生不同签名

Harness（Module 08）用这个签名做**熔断器**：同一签名出现 3 次 → `abort`。

### 3.3 ToolPolicy：角色上限和本次运行授权解耦

```python
AGENT_ACCESS_MATRIX = {
    "collector": AgentAccess(allowed_tools={"web_search", "web_fetch"}),
    "analyst":  AgentAccess(allowed_tools=set()),   # 无工具
    ...
}

class ToolPolicy:
    def allowed_tools(self, agent, context=None):
        role_allowed = get_agent_access(agent).allowed_tools
        if context is None:
            return role_allowed
        profile = context.agent_profiles.get(agent)
        if profile is None:
            return role_allowed
        return role_allowed.intersection(profile.allowed_tools)
```

关键点：

- `AGENT_ACCESS_MATRIX` 是角色能力上限，不是本次运行授权。
- `AgentProfile.allowed_tools` 是本次运行的实际授权，只能收窄，不能扩权。
- `ToolRuntime` 不直接关心 profile 细节，只依赖 `ToolPolicy`。
- 这样后续 Orchestrator 可以按任务配置 Collector 是否能 `web_fetch`，但 Analyst 即使 profile 写了 `web_search` 也不会获得网络权限。

### 3.4 requested_by 是 provenance，不只是装饰字段

```python
def ensure_allowed(self, agent, call, context=None):
    if call.requested_by != agent:
        raise ValueError(
            f"tool call requested_by {call.requested_by} cannot execute as {agent}"
        )
```

`ToolRuntime.execute(agent, call, context)` 必须校验 `call.requested_by == agent`。否则 harness 一旦传错 agent，就可能把 Analyst 请求伪装成 Collector 请求执行，审计日志也会失真。

### 3.5 失败也返回 ToolResult，不抛异常

```python
# disallowed tool → ok=False
ToolResult(ok=False, error="web_search is not allowed for analyst")

# unknown tool → ok=False
ToolResult(ok=False, error="unknown tool: magic_wand")

# tool.run() crashes → ok=False
ToolResult(ok=False, error="ConnectionError: ...")
```

所有错误都收敛为 `ToolResult(ok=False, error=...)`。Harness 不需要 try/except 每个工具调用，只要看 `ok` 字段。这和 Module 07 的 `ModelResponse(ok=False)` 模式一致。

---

## 4. Fake Tools 的设计

```python
class FakeWebSearch:
    name = "web_search"

    def run(self, args: dict) -> dict:
        query = args.get("query", "")
        return {
            "results": [
                {"title": f"Search result for: {query}", ...},
                {"title": f"Analysis: {query}", ...},
            ],
            "total_results": 2,
        }
```

要点：
- **确定性** — 相同 query 永远返回相同结果（测试可重复）
- **自包含** — 无网络、无 API key
- **包含查询词** — 输出里包含输入 query，方便验证"搜索了正确的东西"
- **schema 对齐** — 返回结构模拟真实搜索 API（`results` 数组）

---

## 5. 面试常见追问

**Q: ToolRuntime 和 ModelRuntime 为什么要分开？它们不是都在 runtime/ 下吗？**

A: 虽然都叫 Runtime，但职责不同。Tool Runtime 管**权限 + 调用 + 签名**，Model Runtime 管**provider 适配 + 结构化输出 + usage 统计**。分开的好处：Harness 可以单独 mock ToolRuntime 或 ModelRuntime，互不影响。

**Q: 为什么不直接在 Agent 里调 `requests.get`？**

A: 测试时 Agent 会做真实的网络请求，你没法断言"collector 确实搜了 ACME 而不是什么都没做"。Fake tool 返回确定性的 data，测试可以精确验证 tool 调用和结果。

**Q: 如果要加一个新工具（比如 `database_query`），需要改哪？**

A: 三处：
1. 在角色上限里声明哪些 agent 最多能使用它
2. 在 run profile 里授予本次运行实际允许的工具
3. 实现 `Tool` protocol 的类（`DatabaseQuery`）
4. `ToolRuntime.register(DatabaseQuery())`

Agent 代码本身不用改。

**Q: 为什么不只用 `AgentProfile.allowed_tools`，还要静态矩阵？**

A: Profile 是配置，配置可能写错或被过度授权。静态矩阵是安全上限，表达产品架构里的职责边界：Collector 负责收集证据，Analyst/Writer/Reviewer 在 v0 不直接访问网络。两层相交后，既有灵活性，也不会越权。

**Q: `signature` 用 hash 有什么风险？hash 冲突怎么办？**

A: SHA-256 的碰撞概率在实际场景中可忽略（约 \(10^{-77}\)）。真撞了也就是一次"本应不同的调用被误判为重复"，最坏后果多 abort 一次 — Harness 的 abort 上限是 3 次，不会死循环。

---

## 6. 测试覆盖

```
test_execute_allowed_tool              # Collector 合法调用 web_search
test_execute_web_fetch                 # web_fetch 返回页面内容
test_reject_disallowed_tool            # Analyst 调用 web_search 被拒绝
test_rejects_tool_call_requested_by_another_agent # requested_by 必须匹配执行 agent
test_profile_allowed_tools_can_narrow_static_role_permissions # profile 可以收窄 Collector 工具
test_profile_allowed_tools_cannot_exceed_static_role_permissions # profile 不能给 Analyst 扩权
test_reject_unregistered_tool          # 未注册工具返回错误
test_preview_is_truncated              # preview 是摘要，不是完整数据
test_signature_stable_for_identical    # 相同调用 → 相同签名
test_signature_differs_for_different_args  # 不同参数 → 不同签名
test_signature_differs_for_different_tool  # 不同工具 → 不同签名
test_signature_stable_regardless_of_id     # 签名不依赖 call.id
```
