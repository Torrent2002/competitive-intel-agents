# 学习文档 27：Basic Web Dashboard

## 一句话概括

模块 27 提供一个基于浏览器的最小化 run 检查面板，零外部依赖，只读 workspace stores，绑定 localhost。

## 为什么需要它

终端 dashboard 适合开发者快速检查，但有两类场景不够用：

- **Demo 展示**：给非开发者看 run 结果，终端文字不如一个可点的网页直观。
- **多 run 浏览**：当 workspace 累积了多次 run，点击切换比命令交互更高效。

模块 27 解决的就是这个：不用装任何新依赖，一个 `competitive-intel web` 就能在浏览器里看到 run 列表和每条 run 的完整详情。

## 关键代码

- `src/competitive_intel_agents/web/__init__.py`
  - `render_run_list()` — 从 workspace 读取所有 run results，生成 run 列表页 HTML。
  - `render_run_detail()` — 渲染单条 run 的详情页：status、report、sources、claims、reviewer feedback、journal events、provenance summary、agent rounds、health signals。
  - `WebDashboardHandler` — 基于 `http.server.BaseHTTPRequestHandler`，监听 `/` 和 `/runs/<id>`。
  - `start_web_server()` — 启动阻塞式 HTTP server。

### 为什么用 stdlib 而不用 FastAPI

项目 `pyproject.toml` 的 `dependencies = []`，零外部依赖是设计决策。Web dashboard 是只读面板，不需要表单、auth、session——用 `http.server` 足够，且保持了整个项目的"clone 就能跑"体验。

### CLI 启动

```bash
competitive-intel web --workspace .competitive-intel --port 8080
```

不指定 `--workspace` 默认读取 `.competitive-intel`。

## 面试怎么讲

可以说：

> 我们没有引入任何 web 框架依赖。stdlib `http.server` 做的只读 dashboard，直接读 SQLite artifact store 和 journal store。所有页面都是服务端渲染的纯 HTML/CSS，不需要 JavaScript。这保证了 dashboar 和 CLI 读的是同一份数据，不会出现"CLI 能看到但 web 看不到"的不一致。

## 后续扩展

- 实时刷新（WebSocket 或轮询）。
- run 搜索和过滤。
- 在线上直接触发 re-run。
- artifact 和 claim 的 diff 视图（v1 vs v2）。
