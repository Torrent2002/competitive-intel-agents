# 模块 38：REST API — `/api/` 路由 + Bearer Token 鉴权

## Goal

在现有 `WebDashboardHandler` 的基础上，新增一组以 JSON 为契约的
`/api/*` 端点，让外部系统（CI、curl 脚本、未来的 SDK）能不再走 HTML
表单也能完整使用 collector → analyst → writer → reviewer 流水线。

约束：**不引入第三方 web 框架**（FastAPI / Flask / Starlette），保持
项目「stdlib-only」基调；保留现有 HTML 路由不动；新增的鉴权机制
对老的 PoC 路径完全透明。

## Scope

In scope:

- 新建 `competitive_intel_agents/web/api.py`：
  - `is_api_path(path)` — 判断一个 URL path 是否落在 `/api/` 前缀
  - `handle_api_request(handler, method, workspace)` — 唯一对外入口，
    在路由上分派、统一异常封装、写入响应
- 新增 6 条端点：
  - `POST /api/runs` — 创建 run（real_web/real_model 时 202，纯 fake 时 201）
  - `GET /api/runs?limit=&offset=` — 分页列表，最近的 run 在前
  - `GET /api/runs/{id}` — 单个 run 状态、review_feedback、caveats
  - `GET /api/runs/{id}/report` — 报告（默认 JSON，`Accept: text/markdown` 切 markdown）
  - `GET /api/runs/{id}/sources` — 来源列表
  - `GET /api/runs/{id}/claims` — claim 列表（含 `accuracy` 字段，[[35-claim-source-cross-check]]）
- Bearer Token 鉴权：
  - env `CIA_API_TOKEN` 控制；未设 = 完全开放（兼容现有 localhost PoC）；
    设了 = 全部 `/api/` 请求必须带 `Authorization: Bearer <token>`，
    否则 401
  - 鉴权对所有 GET / POST 一视同仁（claims/sources 也是机密）
- `web/__init__.py` 的 `do_GET` / `do_POST` 顶部各加一行 dispatch：
  ```python
  if is_api_path(parsed.path):
      handle_api_request(self, "GET", self.workspace)
      return
  ```
- 测试 `tests/unit/test_web_api.py`（15 个）：起真实 `ThreadingHTTPServer`，
  通过 `http.client.HTTPConnection` 发请求，覆盖：
  - 创建 run（fake 同步 / real 异步 stub）
  - 校验失败（缺字段 / 非 JSON body）
  - 鉴权（未设 / 错 token / 正确 token / GET 也鉴权）
  - 列表分页 / 单 run 详情 / 不存在 → 404
  - sources / claims / report (JSON + markdown 协商)
  - 未知子路径 → 404

Out of scope:

- 引入任何 web 框架
- 把 HTML 表单 POST 路径改写成 API（保留 `/runs` 给浏览器）
- 多用户 / 多 token / RBAC（PoC 一刀切单 token 够用）
- 长连接事件流（SSE / WebSocket）—— 客户端目前只需轮询 `GET /api/runs/{id}`
- API 版本前缀（`/api/v1/`）—— 现在加版本反而锁死契约，等真有第二版再切

## Design

### 模块结构

```
competitive_intel_agents/web/api.py
  ├── is_api_path(path) -> bool
  ├── handle_api_request(handler, method, workspace) -> None     # 唯一入口
  ├── _ApiError(Exception)                                       # 路由内短路用
  ├── _check_auth(handler) -> bool                               # CIA_API_TOKEN
  ├── _read_json_body(handler) -> Any
  ├── _str_field / _str_list / _parse_int                        # 校验
  ├── _handle_post_runs / _handle_list_runs / _handle_run_subroute
  ├── _write_run_detail / _write_report / _write_sources / _write_claims
  ├── _request_to_form_payload                                   # 复用 form 路径
  ├── _summarize_run / _full_run_payload / _render_report_markdown
  └── _write_json / _write_error                                 # 统一信封
```

### 请求/响应信封

成功：
```json
{"data": {...}, "error": null}
```

失败：
```json
{"data": null, "error": {"code": "not_found|unauthorized|bad_request|method_not_allowed|internal", "message": "..."}}
```

`code` 是稳定字符串（不是数字）—— 客户端可以 `if err.code == "not_found"`
分支，不用解析 prose。`message` 给人看。

### 异步 run 创建

`POST /api/runs` body 里：
- `real_web=True` 或 `real_model=True` → 走 `start_run_from_form`，
  立刻返回 `202 + {"run_id": ..., "status": "running"}`，后台 daemon
  线程跑 orchestrator
- 都不开 → `create_run_from_form` 同步执行（fake pipeline 跑得快），
  返回 `201 + {"run_id": ..., "status": "<final>"}`，省去客户端再做
  一轮轮询

为什么复用 form 路径而不是重新写一份 orchestrator wiring：

- 单一执行入口避免两份「real_web / real_model 默认值」漂移
- form 路径已经覆盖了 `_make_web_orchestrator`、SQLite 持久化、
  background thread 等所有细节
- 适配函数 `_request_to_form_payload` 只有 ~10 行，把 dataclass 映射
  回 form-shaped dict 即可

### 鉴权

```python
def _check_auth(handler):
    expected = os.environ.get("CIA_API_TOKEN", "").strip()
    if not expected:
        return True              # PoC 模式：完全开放
    header = handler.headers.get("Authorization", "") or ""
    if not header.lower().startswith("bearer "):
        return False
    presented = header[len("bearer "):].strip()
    return presented == expected
```

- **不设 token = 不鉴权**：保留「ssh 上去 `pip install -e .` 然后浏览器
  访问 8080」的 PoC 体感；当用户真上线再设 env，自然进入「生产」模式
- **大小写不敏感的 scheme**：HTTP RFC 7235 规定 `Bearer` scheme 不区分
  大小写
- **常量比较 vs 等长比较**：当前用 `==` 直接比，token 是单进程 env，
  不存在跨用户对比；上 KMS / Vault 时再换 `secrets.compare_digest`
- **GET 也鉴权**：没有「公开读 + 鉴权写」的概念，因为 claims 列表本身
  就是机密分析结果

### 路由分派

`do_GET` / `do_POST` 顶部一行：
```python
if is_api_path(parsed.path):
    handle_api_request(self, "GET", self.workspace)
    return
```

`is_api_path` 而不是 `path.startswith("/api/")` 是为了让 `/api`（无尾
斜杠）也命中 → 统一返回 404，不会让 HTML 错误页跳出来吓到客户端。

### 内容协商

`GET /api/runs/{id}/report` 默认返回 JSON。如果 `Accept: text/markdown`
明确要求 markdown，渲染成 `# Report ... ## section ...` 结构。

不做完整的 q-value 解析（`Accept: text/markdown;q=0.9, application/json;q=0.8`）：
- 99% 的客户端不会发 q-value
- 项目当前只有两种格式
- 引入 q-value 解析需要 ~50 行代码 + 测试，带来的复杂度大于收益

## Tests

`tests/unit/test_web_api.py`（15 个），全部起真实 HTTP server：

1. `test_post_runs_creates_run_and_returns_201_for_fake_pipeline` —
   纯 fake → 201 + 终态 status
2. `test_post_runs_accepts_real_flags_and_returns_202` — stub
   `start_run_from_form` 验证 202 + `status="running"`
3. `test_post_runs_rejects_missing_company_with_400` — 字段缺失
4. `test_post_runs_rejects_invalid_json_body_with_400` — 非法 JSON
5. `test_post_runs_requires_bearer_token_when_env_set` — 三态：无
   header / 错 token / 正确 token
6. `test_auth_skipped_when_token_unset` — env 未设 → GET 直接 200
7. `test_auth_applies_to_get_routes` — 鉴权对 GET 也生效
8. `test_get_runs_returns_paginated_list` — limit/offset + 最新优先
9. `test_get_run_detail_returns_full_state` — review_feedback +
   caveats 都序列化
10. `test_unknown_run_returns_404` — 错误 ID
11. `test_get_sources_returns_artifact_list`
12. `test_get_claims_includes_accuracy_field` — [[35-claim-source-cross-check]]
    引入的字段在 API 响应里
13. `test_get_report_returns_json_by_default`
14. `test_get_report_negotiates_markdown` — Accept header 切格式
15. `test_unknown_api_route_returns_404`

## Backward compatibility

- HTML 路径完全不动：`/`、`/runs`、`/runs/{id}`、`/runs/{id}/export`、
  `/workflow` 行为零变化；浏览器书签和 form 提交都按原样工作
- `CIA_API_TOKEN` 默认未设 = 现有所有部署的 `/api/` 都开放，不会因为
  升级镜像突然 401
- 没新增任何依赖

## Related

- [[36-rate-limiting]] — `POST /api/runs` 引发的搜索调用走同一套
  per-engine token bucket
- [[37-structured-logging]] — API handler 的异常 / 鉴权失败都记录到
  统一 logger，可以聚合
- [[35-claim-source-cross-check]] — `accuracy` 字段在 `/api/runs/{id}/claims`
  原生暴露
- [[39-deployment]] — Docker 镜像默认 `CIA_API_TOKEN` 不设；
  生产部署在 docker-compose 的 `env_file` 里设 token，镜像不动
