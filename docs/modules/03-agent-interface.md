# 03 Agent Interface

## Goal

Define the minimal contract every agent must implement.

## Scope

In scope:

- Agent name.
- Agent profile.
- Round input.
- Round output.
- Progress signals.
- Agent data access boundaries.

Out of scope:

- Prompt templates.
- Model-specific adapters.
- Agent-specific reasoning.

## Public Interface

```python
class Agent(Protocol):
    name: AgentName

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        ...
```

## AgentRoundResult

Should include:

- `completed`
- `tool_calls`
- `output_artifact_ids`
- `signals`
- `message`
- `error`

## Data Access Matrix

Agents should receive narrow repository/tool/model capabilities instead of unrestricted shared state.
The matrix is the role-level ceiling; run-specific `AgentProfile.allowed_tools`
can only narrow it.

| Agent | May Read | May Write | May Use Tools |
|---|---|---|---|
| Collector | Run request, prior collector sources | Source artifacts | `web_search`, `web_fetch` |
| Analyst | Active source artifacts, reviewer feedback for analyst | Analysis claims | none |
| Writer | Active analysis claims, active source metadata, reviewer feedback for writer | Report drafts | none |
| Reviewer | Active report draft, active claims, active sources | Review feedback | none |

Rules:

- Agents do not write journal events directly. The harness owns journaling.
- Writer should not read raw fetched pages directly; it should consume claims and source metadata.
- Analyst should not call web tools; missing evidence should become reviewer feedback routed to Collector.
- Reviewer should not mutate artifacts; it only approves or returns feedback.
- `AGENT_ACCESS_MATRIX.allowed_tools` defines maximum role capability, not a per-run grant.
- `AgentProfile.allowed_tools` defines the effective grant for a specific run and must be intersected with the role ceiling.
- Tool execution must reject any `ToolCall` whose `requested_by` does not match the agent currently being run.
- Downstream modules should depend on narrow policy/resolver interfaces instead of importing the matrix directly when they need effective permissions.

## Tests

- Fake agent can complete.
- Fake agent can request tool calls.
- Fake agent can emit output artifact ids.
- Agent access boundaries are represented by test doubles or narrow interfaces.

## Done Criteria

- Harness can run any conforming agent through `competitive_intel_agents.agents.Agent`.
- Agent implementations do not write journal events directly.
- Tool permissions cannot be expanded by run configuration beyond the static role boundary.

## 中文学习笔记

### 一句话定位

Agent Interface 定义了所有 agent 必须遵守的最小协议，同时把每类 agent 的读写权限和工具权限收窄。

### 面试中怎么讲

在多 agent 系统里，最危险的是每个 agent 都变成“什么都能读、什么都能写、什么工具都能调”的万能对象。这样短期看起来方便，但后面 provenance、review、rework、权限控制都会混乱。

所以 03 这个模块先不实现具体 Collector 或 Analyst，而是定义所有 agent 的统一 contract：每个 agent 有一个 `name`，并实现 `run_round(context, state) -> AgentRoundResult`。Harness 后续只依赖这个接口，不关心具体 agent 内部怎么工作。

同时我们定义 `AgentAccess` 和 `AGENT_ACCESS_MATRIX`，明确 Collector、Analyst、Writer、Reviewer 分别可以读什么、写什么、用什么工具。这样后续模块实现时不会随意越界。

### 关键设计点

- `Agent` 是 `Protocol`，表示结构化接口：只要对象有 `name` 和 `run_round`，就可以被 harness 使用。
- `BaseAgent` 提供默认基类，未实现 `run_round` 时会抛 `NotImplementedError`，避免静默失败。
- `AgentRoundResult` 仍然来自 Core Models，Agent Interface 不重复定义数据结构。
- `AgentAccess` 把权限拆成 `may_read`、`may_write`、`allowed_tools` 三类。
- `ensure_tool_allowed()` 用 agent name 检查工具权限，Collector 可以用 `web_search/web_fetch`，其他 agent 在 v0 不能用 web tools。
- Agent 不直接写 journal event；journal 是 harness 的职责，这样每轮记录才能统一。

### 核心对象怎么串起来

一个 agent round 可以这样理解：

1. Harness 准备 `RunContext` 和当前 `AgentState`。
2. Harness 调用符合 `Agent` 协议的对象。
3. Agent 返回 `AgentRoundResult`，里面可能包含完成状态、工具请求、产物 id、progress signals 或错误。
4. Harness 根据 `AgentRoundResult` 决定继续、停止、重试、返工或中止。
5. Harness 负责写 journal，agent 本身不碰审计日志。

### 可以被追问时怎么答

如果问为什么用 `Protocol` 而不是只用继承，可以说：Protocol 更适合定义“行为契约”，具体 agent 不一定非要继承某个基类，只要结构符合就能被 harness 使用；这让测试 fake agent 和未来真实 agent 都更灵活。

如果问为什么还保留 `BaseAgent`，可以说：Protocol 提供结构约束，BaseAgent 提供一个方便的实现起点。真实 agent 可以继承 BaseAgent，也可以只实现 Protocol。

如果问为什么限制 Analyst/Writer 使用 web tools，可以说：这是为了保持数据流清晰。Collector 负责收集证据，Analyst 负责基于证据推理，Writer 负责组织表达。如果 Writer 直接上网查资料，报告里的 claim provenance 就会绕过 Analyst 和 Reviewer 的验证链路。

如果问权限矩阵是不是过度设计，可以说：它现在只是轻量常量和检查函数，不是复杂权限系统。但它提前固定边界，能防止后续模块实现时越界，是低成本高收益的工程约束。
