# 学习文档 27：Basic Web Dashboard

## 一句话概括

**模块 27 提供一个基于浏览器的 run 检查面板：详情页先展示四个 agent 的协作状态和 workflow map，再展示 report、sources、claims、journal 等表格。**

## 为什么需要它

终端 dashboard 适合开发者快速检查，但非开发者更需要“看见四个 agent 在协作”：

- Collector 是否在收集；
- Analyst 是否卡住；
- Writer 是否已产出报告；
- Reviewer 是否要求 rework；
- rework 是回到 collector、analyst，还是 writer。

所以 run detail 页的优先级是：

```text
Run status -> Workflow Map -> Agent Workflow -> Report -> Tables
```

## 关键代码

- `src/competitive_intel_agents/web/__init__.py`
  - `render_run_list()`：workspace run 列表。
  - `render_workflow_map()`：协作路径、返工路径、状态契约。
  - `render_agent_workflow()`：四个固定 agent 卡片。
  - `render_run_detail()`：report、sources、claims、feedback、journal、provenance。
  - `WebDashboardHandler`：监听 `/`、`/runs/<id>`、`/workflow`。
  - `start_web_server()`：启动阻塞式 HTTP server。

## Agent Workflow 状态

前端不维护单独状态机，而是从数据推断：

- `RunResult.status`
- `RoundEvent.decision`
- `RoundEvent.agent`
- `ReviewFeedback.target_agent`

常见显示状态：

| UI State | Meaning |
|---|---|
| `pending` | agent 尚未开始 |
| `running` | run 仍在执行，当前 agent 没有 stop/rework/abort |
| `done` | agent 当前阶段完成 |
| `rework` | reviewer 或 rework loop 指向该 agent |
| `blocked` | 上游失败导致该 agent 没机会执行 |
| `aborted` | agent abort 或 run aborted |

运行中 agent 卡片内部显示 thinking animation，边框显示流光效果；run 仍是
`running` 时页面自动刷新。

## Source Metadata 展示

Source 表格优先保持可读，但应展示关键 evidence metadata：

- `content_ref`
- `char_count`
- `covered_dimensions`
- `source_score`
- `extract_quality`

这样用户可以判断 report 是基于完整 source，还是只拿到了很薄的摘要。

## 为什么用 stdlib 而不用 FastAPI

项目保持零外部依赖。Dashboard 是只读面板，不需要表单、auth、session。
用 `http.server` 足够，并保证 CLI 和 Web 读的是同一份 workspace 数据。

## CLI 启动

```bash
competitive-intel web --workspace .competitive-intel --port 8080
```

不指定 `--workspace` 默认读取 `.competitive-intel`。

## 面试怎么讲

> Web dashboard 不是另一个状态系统，它只是把 journal、artifacts、RunResult 和 ReviewFeedback 读出来。详情页先显示四个 agent 的协作状态，让用户看到 collector/analyst/writer/reviewer 的推进和返工，再看 report 和表格。running 时自动刷新，active agent 有 thinking 动画；source 表格还能展示 content_ref 等证据 metadata。
