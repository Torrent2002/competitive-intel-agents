# 学习文档 38：REST API + Bearer Token 鉴权

## 一句话概括

**HTML form 表单 → JSON REST API**：把现有 `WebDashboardHandler` 的
form-encoded `POST /runs` 升级为 6 条 `/api/*` 端点，统一信封 + 一致的
错误码 + 可选 Bearer Token，**不引第三方 web 框架**。

## 为什么需要它

### 触发改动的真实场景

P1 issue #14 的需求：「外部系统能 curl 触发分析」。当前能做到吗？
看现有 form path：

```bash
curl -X POST http://127.0.0.1:8080/runs \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "company=Notion&market=productivity&competitors=Coda,Airtable&questions=pricing"
# → 303 redirect 到 /runs/{id} 的 HTML
```

问题：
1. **响应是 HTML**，外部系统得 grep `<title>` / 解析 DOM 才能知道 run_id
2. **无错误信封**：参数错了直接渲染 HTML 错误页，没 `code` 字段
3. **无鉴权**：localhost 8080 一旦反代到外网就裸奔
4. **无 claims/sources/report 直读端点**：只能再爬 HTML / 走 SQLite

### 为什么不上 FastAPI

考虑过：
1. `FastAPI` — 30 行起步，pydantic 校验、自动 OpenAPI 文档
2. `Flask` — 轻量但还是依赖 Werkzeug + Jinja
3. 自实现路由 on `BaseHTTPRequestHandler` — 100 行解决问题

最终选 #3。理由：

- 项目当前只有 1 个核心依赖（curl_cffi），dependencies 加了 FastAPI
  会带 starlette + pydantic + uvicorn 一串
- 需求窄：6 条端点、JSON in/out、bearer token —— pydantic 90% 功能用
  不到，OpenAPI 自动文档当前没人用
- 现有代码已经在用 `BaseHTTPRequestHandler`，加一行 dispatch 就接进去；
  上 FastAPI 反而要重写 web 启动逻辑、重写 form 路径
- 反例：如果将来要 SSE / WebSocket / OpenAPI 文档对外，**那时**再切 FastAPI

### 路由分派的最小入侵设计

`web/__init__.py` 现有 `do_GET` / `do_POST` 加 2 行：

```python
def do_GET(self):
    parsed = urlparse(self.path)
    if is_api_path(parsed.path):           # ← 新增
        handle_api_request(self, "GET", self.workspace)
        return                              # ←
    if parsed.path == "/":
        ...                                 # 现有 HTML 逻辑不动
```

`is_api_path` 比 `path.startswith("/api/")` 多匹配了 `/api`（无尾斜杠）：

```python
def is_api_path(path):
    return path == "/api" or path.startswith("/api/")
```

否则访问 `/api`（漏写尾斜杠）会落到 HTML 404 页面，对 API 客户端体感
不一致。统一交给 `handle_api_request` 返回 JSON 404。

## 关键代码

### 1. 统一错误信封

```python
# 成功
{"data": {...}, "error": null}

# 失败
{"data": null, "error": {"code": "not_found", "message": "run not found: run_xyz"}}
```

`code` 是稳定字符串（`not_found` / `unauthorized` / `bad_request` /
`method_not_allowed` / `internal`），客户端可以分支：

```python
if resp.json()["error"]["code"] == "unauthorized":
    refresh_token()
```

不是数字（HTTP status code）—— 因为 `bad_request` 既可能是 422 也可能
是 400，`code` 提供语义层；HTTP 层留给基础设施（CDN、reverse proxy）。

### 2. `_ApiError` 短路

每个 route handler 用 raise 跳出，由顶层 `handle_api_request` 统一接住：

```python
class _ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message

# inside handler
def _str_field(body, key, *, required):
    value = body.get(key, "")
    if not isinstance(value, str):
        raise _ApiError(400, "bad_request", f"field {key!r} must be a string")
    ...

# top
try:
    if method == "POST" and path == "/api/runs":
        _handle_post_runs(...)
        return
    ...
except _ApiError as exc:
    _write_error(handler, exc.status, exc.code, exc.message)
except Exception as exc:
    logger.exception("api handler crashed", extra={"path": path})
    _write_error(handler, 500, "internal", str(exc))
```

vs `if not body.get("company"): return _write_error(...)` 风格 —— exception
集中管理 status/code，校验代码本身只关心 happy path。

### 3. Bearer Token 鉴权

```python
def _check_auth(handler):
    expected = os.environ.get("CIA_API_TOKEN", "").strip()
    if not expected:
        return True              # PoC 模式：env 没设 = 完全开放
    header = handler.headers.get("Authorization", "") or ""
    if not header.lower().startswith("bearer "):
        return False
    return header[len("bearer "):].strip() == expected
```

设计要点：

1. **「未设 token = 不鉴权」**：兼容现有 PoC（ssh 上去启 8080 就用）。
   当 ops 把容器跑到外网时，docker-compose `env_file` 设个 token，
   立刻进入「生产」模式，**镜像不变**。

2. **scheme 不区分大小写**：`bearer foo` 和 `Bearer foo` 都接受，
   RFC 7235 §2.1 强制要求。

3. **当前用 `==` 直接比**：单进程 env、单 token，无 timing attack 表面。
   上 KMS / DB-backed token 时换 `secrets.compare_digest`。

4. **GET 也鉴权**：没有「公开读 + 鉴权写」的概念。claims / sources
   是机密分析结果，不能让 GET 漏出去。

### 4. 异步 run 创建

```python
def _handle_post_runs(handler, workspace):
    body = _read_json_body(handler)
    company = _str_field(body, "company", required=True)
    ...
    request = CompetitiveIntelRequest(company=company, ...)

    # Lazy import：测试可以 monkeypatch 这个符号
    from competitive_intel_agents.web import create_run_from_form, start_run_from_form

    form = _request_to_form_payload(request, real_web=real_web, real_model=real_model)
    if real_web or real_model:
        result = start_run_from_form(workspace, form)   # 后台 daemon thread
        status_code = 202
    else:
        result = create_run_from_form(workspace, form)  # 同步跑完
        status_code = 201
    _write_json(handler, status_code, {"data": {"run_id": result.run_id, "status": result.status}, "error": None})
```

为什么 fake pipeline 走 201 同步，real 走 202 异步：

- fake pipeline ~50ms 跑完，等它返回比客户端再发一次轮询便宜
- real pipeline 几十秒到几分钟，必须 202 + 后台线程，否则连接会被
  反代 / load balancer timeout 切掉

为什么复用 `create_run_from_form` / `start_run_from_form`：

- `_make_web_orchestrator` 已经把 real_web / real_model / max_wall_time
  / SQLite 持久化全连好了；API 再写一份会漂移
- 适配只需 `_request_to_form_payload`：
  ```python
  return {
      "company": [request.company],
      "market": [request.market or ""],
      "competitors": [", ".join(request.competitors)],
      "questions": [", ".join(request.questions)],
      "real_web": ["1"] if real_web else [],
      ...
  }
  ```

### 5. 内容协商：JSON vs Markdown

```python
def _write_report(handler, workspace, run_id):
    ...
    accept = handler.headers.get("Accept", "") or ""
    if "text/markdown" in accept and report is not None:
        body = _render_report_markdown(report).encode("utf-8")
        # 直接写 markdown 响应
        return
    # 默认 JSON 响应
```

不做完整 q-value 解析（`Accept: text/markdown;q=0.9, application/json;q=0.8`）：

- 99% 客户端不发 q-value，发的也基本就是单一类型
- 引入 q-value 解析需要 ~50 行代码 + 测试，复杂度 > 收益
- 业务只有两种格式，substring `in` 够用

## 设计取舍

### 为什么不加 `/api/v1/` 版本前缀

加版本的代价：
- 客户端 URL 全部带前缀
- 老 client 升级阻力
- 一开始就锁死「v1 永远向后兼容」

不加版本的代价：
- 真有破坏性变更时只能改 contract docs

权衡：当前只有 6 条端点，用户都是内部 + 自己写的客户端。等客户端
量级到 10+ 或要对外开放 SDK 时再补 `/api/v1/`，老路径 redirect 过去。
**现在加版本前缀是过早抽象。**

### 为什么 `report` 默认返回 JSON 而不是 markdown

理由：API 客户端默认用程序解析，不是给人看的。

- 程序解析：`response["data"]["sections"]["Overview"]` 直接拿到 string
- 给人看：浏览器看 dashboard、CLI 看 export，都是已有路径

`Accept: text/markdown` 是 escape hatch，让 ops 能 `curl` 一行读报告。

### 为什么 `_write_error` 不带 stack trace

500 错误时只返回 message，不返回 traceback —— 因为：
- traceback 暴露文件路径 / 内部模块名 → 攻击面
- 客户端拿 traceback 也修不了 server bug
- 真要 debug 走 `logger.exception`，traceback 落到 stderr / log file
  里 ops 可见，**响应里看不到**

### 为什么 list_runs 反转顺序而不让 SQLite ORDER BY

`workspace.list_run_results()` 返回所有 run（runs.json 反序列化），
**没有 SQL 层 LIMIT/OFFSET**。当前 PoC 量级（< 100 runs）反转 + 切片
够用。运行规模上千时把 `list_run_results` 改成 SQL 分页，API 层不动。

这是「先解决问题，可观测瓶颈再优化」的典型场景：现在加 SQL 层是过早
优化。

### 为什么 lazy import `create_run_from_form` / `start_run_from_form`

```python
def _handle_post_runs(handler, workspace):
    ...
    from competitive_intel_agents.web import create_run_from_form, start_run_from_form
```

不是从 `api.py` 顶部 import。理由：

- **避免循环 import**：`web/__init__.py` import `web/api.py`，
  反过来 `web/api.py` 顶部如果 import `web` 就死锁
- **测试 monkeypatch 友好**：测试用例可以
  ```python
  monkeypatch.setattr("competitive_intel_agents.web.api.start_run_from_form", fake_start)
  ```
  让测试不真的开 daemon thread。

## 测试

`tests/unit/test_web_api.py` 15 个，全部起真实 `ThreadingHTTPServer`，
`http.client.HTTPConnection` 发请求。**不 mock HTTP**：

1. `test_post_runs_creates_run_and_returns_201_for_fake_pipeline` — 同步路径
2. `test_post_runs_accepts_real_flags_and_returns_202` — 异步 stub
3. `test_post_runs_rejects_missing_company_with_400`
4. `test_post_runs_rejects_invalid_json_body_with_400`
5. `test_post_runs_requires_bearer_token_when_env_set` — 无 / 错 / 对
6. `test_auth_skipped_when_token_unset`
7. `test_auth_applies_to_get_routes`
8. `test_get_runs_returns_paginated_list`
9. `test_get_run_detail_returns_full_state` — review_feedback + caveats
10. `test_unknown_run_returns_404`
11. `test_get_sources_returns_artifact_list`
12. `test_get_claims_includes_accuracy_field` — [[35-claim-source-cross-check]]
13. `test_get_report_returns_json_by_default`
14. `test_get_report_negotiates_markdown` — Accept: text/markdown
15. `test_unknown_api_route_returns_404`

为什么不 mock HTTPServer：
- HTTP 层 bug（content-type / status / 重定向）肉眼看不出，必须真实 socket 验
- `BaseHTTPRequestHandler.do_GET` 内部状态多，mock 容易漏

## 面试要点

1. **何时引框架，何时自己写**：核心判断是「需求形状」是否匹配框架的
   抽象。当前需求 = 6 条 JSON 端点 + 单 token + form 路径复用，
   `BaseHTTPRequestHandler` + `_ApiError` 短路 + `_write_json` 100 行
   解决；上 FastAPI 是「为了用而用」。

2. **错误码是字符串而不是 HTTP status**：`code` 给客户端语义分支用，
   HTTP status 给基础设施用，两层职责。等 HTTP 层 reverse proxy
   改写状态码（429 → 503）时，`code` 仍稳定。

3. **`CIA_API_TOKEN` 设了就鉴权 / 不设就开放**：保留 PoC 体感的关键。
   ops 升级到生产「只改一个 env，镜像不动」，不是「升级到 v2 镜像
   强制 token」。

4. **lazy import 解决循环 + monkeypatch**：当 A → B → A 形成循环时
   不一定要改架构，函数内 import 是合法且常见的解药；同时测试用
   `monkeypatch.setattr("path.to.symbol")` 才能命中正确的查找点。

5. **「先反转再切片」vs「SQL ORDER BY LIMIT」**：在数据量规模 <
   1000 时，Python 内存反转是 O(n) 但 cache-friendly，比 SQL 多一次
   IO 还快。优化器有时是「不要现在优化」。

6. **真实 HTTP 测试 vs mock**：HTTP 协议层很多坑（Content-Length、
   chunked transfer、Connection keepalive）只有真起 socket 才暴露；
   mock `BaseHTTPRequestHandler` 很容易把假阳性当成 pass。

7. **`Accept: text/markdown` substring 而不是 q-value**：q-value
   解析有 RFC 复杂度，业务收益小；先 substring 满足 90%，等真有
   多格式需求再升级。这是「过早抽象」的反面 —— **过早完美**。
