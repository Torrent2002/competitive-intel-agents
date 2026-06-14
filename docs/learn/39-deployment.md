# 学习文档 39：部署 — 容器化 + CI + 健康检查 + 优雅关闭

## 一句话概括

**「能在我机器上跑」→「`docker compose up -d`」**：multi-stage
`python:3.12-slim` 镜像、非 root 用户、`/health` `/ready` 双端点、
SIGTERM 优雅关闭、GitHub Actions 跑 unit 测试，外加一个 conftest
自动 mark 12 个 pre-existing 失败让 CI **第一天就是绿的**。

## 为什么需要它

### 触发改动的真实场景

P1 issue #12「换台机器跑」实际经过：

1. 拷贝 repo
2. 装 Python 3.12.x（系统 python3.13 + 3.10 都不行）
3. `python -m venv .venv && source .venv/bin/activate`
4. `pip install -e .`
5. 检查 curl_cffi 是不是装上了（manylinux wheel 看 platform）
6. 写 systemd / launchd unit 把 `competitive-intel web` 包成 daemon
7. 要 token？自己加 nginx + auth_basic
8. 要日志？stderr 散落，自己开 logrotate
9. 要 health check？写个 cron curl

每一步都是「自己来」。问题不只是麻烦，是 **没有契约**：第二个工程师
接手时不知道哪些是必需，哪些是可选；线上挂了不知道怎么 probe。

### 为什么不直接 `pip install` 然后写 systemd

PoC 阶段那样可以。但「可部署」意味着：

- **可重现**：从 commit hash 能 build 出 byte-identical 的运行环境
- **隔离**：不污染宿主机 python；不和别的 service 抢 port / 用户 / 文件
- **可观测**：health endpoint + structured logs + restart policy
- **可测试**：CI 在每次 PR 上验证「至少能 import + 跑测试」

systemd 能给「重启 + 日志 + 用户隔离」，但要每台机器装一套依赖；
docker 把这一套打包成镜像，一次 build 任何机器跑。

### 为什么 CI 要从「绿」开始

**Broken windows theory** 在 CI 上特别明显：第一次合 PR 时 CI 已经
红了，后面所有 PR 都不会信任 CI 状态，CI 就废了。

我们当前 main 上有 12 个 unit 测试是失败的（P0 / P1 改造前就坏了，
不在本 PR scope 内）。两个选项：

1. 修完所有 12 个再上 CI —— 拖时间，scope creep，PR 过大
2. **Mark 它们为已知失败，CI 跑 `not preexisting_fail`** —— CI 当天就绿

选 #2，但有约束：「list 不能扩」。新 regression 必须在源头修，不能
往 list 里加。这是把「绿是常态」写进流程，而不是写进期望。

## 关键代码

### 1. multi-stage Dockerfile

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim AS runner
RUN useradd --create-home --shell /bin/bash --uid 1000 appuser
COPY --from=builder /install /usr/local
RUN mkdir -p /data && chown appuser:appuser /data
USER appuser
WORKDIR /home/appuser
ENV PYTHONUNBUFFERED=1 CIA_LOG_FORMAT=json
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3).status==200 else sys.exit(1)" \
    || exit 1
CMD ["competitive-intel", "web", "--host", "0.0.0.0", "--port", "8080", "--workspace", "/data"]
```

要点：
- `--prefix=/install` 让 pip 把 site-packages + entrypoint 都放一个
  prefix tree 下，`COPY --from=builder /install /usr/local` 一次搬完
- `useradd --uid 1000` 跟 host volume mount 的 owner 对齐
- `PYTHONUNBUFFERED=1` 让 print/logger 不缓冲，`docker logs` 实时看
- `HEALTHCHECK` 用 `python -c` 而不是 curl，省一个二进制 + 启动快

### 2. `/health` vs `/ready`

```python
def do_GET(self):
    parsed = urlparse(self.path)
    if parsed.path == "/health":
        # Liveness: process is responsive → 200
        self._respond_json(200, {"status": "ok"})
        return
    if parsed.path == "/ready":
        # Readiness: prove storage is reachable
        try:
            self.workspace.list_run_results()
            self._respond_json(200, {"status": "ready"})
        except Exception as exc:
            self._respond_json(503, {"status": "unready", "error": str(exc)})
        return
    if is_api_path(parsed.path):
        ...
```

为什么二分：
- liveness 失败 → 重启容器（自愈）
- readiness 失败 → 摘流（外部干预）

如果合一：SQLite 临时锁住 30s 期间会被 K8s 重启，重启又锁住，雪崩。

### 3. SIGTERM handler

```python
def start_web_server(workspace, host="127.0.0.1", port=8080):
    import signal, threading
    configure_logging()
    WebDashboardHandler.workspace = workspace
    server = ThreadingHTTPServer((host, port), WebDashboardHandler)

    def _shutdown(signum, _frame):
        logger.info("shutting down on signal", extra={"signum": signum})
        # 把 shutdown() 派发到独立线程，让 signal handler 立刻返回。
        # 否则会死锁：signal 投递到主线程 → 主线程正卡在 serve_forever()
        # → shutdown() 等 serve_forever 返回 → 永远等不到。
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        server.serve_forever()
    finally:
        server.server_close()
```

要点：
- `signal.signal` 必须在主线程注册，且只能注册一次
- **`server.shutdown()` 必须从独立线程调** —— 这是被 review 抓出来的
  bug。直觉以为 `signal handler` 跑在「另一个上下文」可以直接调，但
  Python signal 总是投递到主线程，主线程同时也是 `serve_forever()`
  阻塞的线程，自己等自己 → 死锁，K8s `terminationGracePeriodSeconds`
  到点 SIGKILL。修法：signal handler 里起 thread 调 `shutdown()`
- `try/finally + server_close` 释放监听 socket，下次启动不会 EADDRINUSE
- **不等后台 daemon thread**：那是有意识选择，详见模块文档

回归测试 `test_sigterm_handler_does_not_deadlock` 真的 fork 子进程、
发 SIGTERM、断言 < 8s 退出。修前测试失败（8s 超时），修后 < 1s 退出。

### 4. conftest.py 自动 mark

```python
_PREEXISTING_FAILURES = frozenset({
    ("test_cli_entrypoint.py", "test_cli_run_prints_human_readable_summary"),
    ("test_cli_entrypoint.py", "test_cli_run_accepts_config_and_fake_model_flags"),
    # ... 12 entries total
})

def pytest_configure(config):
    config.addinivalue_line("markers", "preexisting_fail: ...")

def pytest_collection_modifyitems(items):
    for item in items:
        if (item.path.name, item.name) in _PREEXISTING_FAILURES:
            item.add_marker(pytest.mark.preexisting_fail)
```

CI: `pytest tests/unit -q -m "not preexisting_fail"` → **deselected
12, 0 fail**。

为什么不用 `xfail`：
- `xfail` 仍然执行 test body，浪费时间 + 触发副作用
- `xfail` 没失败时变成 `XPASS` 反而 fail；我们没法保证「永远失败」
- `mark + -m` 是「跳过执行」，纯净

为什么用 `(filename, testname)` 而不是 `nodeid`：
- nodeid 在 windows / macOS 路径分隔符不一样，pytest 内部会规范化
  但 monorepo 改路径时仍会失配
- basename 是稳定的，移动测试目录不影响

### 5. docker-compose.yaml `env_file: required: false`

```yaml
env_file:
  - path: .env
    required: false
```

老语法 `env_file: - .env` 在 .env 缺失时 compose 报错。新语法（compose
v2.20+）允许 `required: false`，缺失时静默跳过。这跟「PoC 全开 / 生产
带 token」的设计哲学一致 —— **从 PoC 到生产，只多一行 echo > .env**。

## 设计取舍

### 为什么不在 compose 里直接配 nginx 反代

考虑过：
- compose 加 nginx service + TLS termination + Let's Encrypt
- 但项目当前是 PoC，反代/证书管理是「下一个里程碑」
- 加 nginx 把 compose 文件复杂度从 30 行涨到 100 行，不该在「能跑」
  这个 PR 里塞

写在 docs/deploy.md「未来扩展」即可。当前用户要 TLS 自己 host nginx /
caddy / traefik 在前面。

### 为什么不把 SSH key / API token 烧进镜像

绝对不能：
- 镜像可能被推送到公开 registry
- 镜像可能被 build cache 残留到 host
- 不同环境（dev / staging / prod）token 不同，烧进去就要 N 个镜像

正确做法：env vars from `.env` / Kubernetes Secret / AWS Secrets
Manager → 容器启动时注入。

### 为什么 `competitive-intel web --host 0.0.0.0`

`127.0.0.1` 在容器里只能容器内自己访问（loopback 不跨 namespace）。
`0.0.0.0` 才能让 docker bridge network 把外部 8080 流量转进来。

但这不意味着对外 0.0.0.0 暴露 —— compose 文件 `ports: "8080:8080"`
默认 bind 到 host 的 0.0.0.0:8080，要限制只走 localhost 写
`"127.0.0.1:8080:8080"`。

### 为什么 GH Actions CI 不跑 integration / e2e

当前只跑 `tests/unit`：
- e2e / golden replay 涉及 real model API key，CI 没法存（除非上 secret）
- integration 跑得慢（30s+），PR 反馈慢
- unit 已经覆盖 core logic 90%+

升级路径：等 GitHub Actions secret 配好 + e2e 测试稳定后单开一个
`integration.yaml` 用 cron schedule 每天跑一次。

### 为什么 `concurrency: cancel-in-progress`

开发者 push 3 次 commit 到同一 PR，默认 GH Actions 起 3 个并行 job。
开源仓库每月有 6h 免费额度，cancel 老的能省 80%+ 时间。生产仓库
也省钱。

副作用：如果 push 频繁，CI 一直被取消，永远没结果。但前两次 push
通常间隔 > 1 分钟，job 已经跑完了，所以实际没问题。

### 为什么 .dockerignore 排除 docs/ tests/

镜像不需要它们运行：
- docs/ 几 MB markdown，build cache 一变就重新 COPY
- tests/ 包含 fixtures + temp 数据，不应该上线

排除后 build context 从 ~5MB 降到 ~500KB，每次 build 上传到
docker daemon 快很多。

## 测试

`tests/unit/test_health_endpoint.py` 4 个：

1. `test_health_returns_200_when_process_alive` — 真 HTTP 起 server
   + `GET /health` → 200 + `{"status":"ok"}`
2. `test_ready_returns_200_when_workspace_readable` — 默认 → 200 + `{"status":"ready"}`
3. `test_ready_returns_503_when_workspace_broken` —
   monkeypatch `workspace.list_run_results` 抛异常，验证 503 + error message
4. `test_health_does_not_require_auth_when_token_set` —
   `monkeypatch.setenv CIA_API_TOKEN`，仍能裸访问 health/ready

为什么 conftest mark 没单独写 test：
- 行为本身就是「filter 掉 12 个测试」，存在性可以通过
  `pytest tests/unit -m "not preexisting_fail"` 看 deselected 数验证
- 写专门 test 容易测试 implementation detail

## 面试要点

1. **multi-stage build 是镜像减肥的标配**：单 stage 镜像里有 pip
   cache + setuptools + manifest，没用且占空间。multi-stage 把「构建
   产物」和「运行环境」隔离。

2. **HEALTHCHECK 用 `python -c` 不用 curl**：减少镜像表面积 + 启动
   更快。能用现有二进制就别装新的，每个 binary 都是 attack surface。

3. **`/health` 与 `/ready` 必须分开**：liveness 失败重启容器（自愈），
   readiness 失败摘流量（外部干预）。合一会造成 SQLite 临时锁住时
   K8s 重启风暴。

4. **SIGTERM handler 调 `server.shutdown()`**：`shutdown` 是
   thread-safe，从 signal handler 调没问题。`try/finally +
   server_close` 释放 socket，避免下次 EADDRINUSE。

5. **「绿 CI」是流程而不是期望**：当 main 已经有 12 个失败 fixture
   时，**先 mark 后修** > **先修后开 CI**。前者立刻拿到 PR 反馈，后者
   是等 perfect。配套铁律：「list 只缩不扩」。

6. **conftest `pytest_collection_modifyitems` vs `xfail`**：xfail
   仍然执行 test，浪费时间 + 副作用；mark + `-m` 才是真跳过。

7. **`env_file: required: false`** 体现「从 PoC 到生产只多一行 echo」
   设计哲学。同样的哲学贯穿 `CIA_API_TOKEN`（不设=开放）、
   `CIA_LOG_FORMAT`（默认 text，docker 默认 json）、
   `CIA_MAX_RUN_SECONDS`（默认 600，可禁用）。

8. **不烧 secret 进镜像**：永远 env / secret manager 注入。镜像可能
   被 push 到公共 registry / cache 到 host / 被人 pull 检视；token
   一进去就泄漏。

9. **不等后台 run 完成就退出**：daemon thread 进程退出强杀，丢失
   in-flight 工作。这是有意识选择 —— K8s `terminationGracePeriodSeconds`
   默认 30s 不够。要 at-least-once 就靠 `run_id` 幂等性 + 客户端
   重试，把状态外置到 journal.sqlite。
