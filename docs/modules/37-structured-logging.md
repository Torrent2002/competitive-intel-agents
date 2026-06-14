# 模块 37：结构化日志 — replace `print(file=sys.stderr)`

## Goal

把散落在各 agent / runtime 的 ad-hoc `print(file=sys.stderr)` 统一替换
成项目级 `logging.Logger` 体系，每条日志自带 `run_id` / `agent` /
`round` 等结构化字段，输出格式可在 `text` / `json` 间切换，level
可过滤，输出目标可重定向到文件。前提：不引入第三方依赖。

## Scope

In scope:

- 新建 `competitive_intel_agents/logging.py`：
  - `get_logger(name)` 拿到带项目命名空间的 Logger
  - `get_run_logger(name, run_id, agent, round, **extra)` 拿 `LoggerAdapter`
    把上下文绑死，每条记录自动带这些字段
  - `JsonFormatter` / `TextFormatter` 自实现
  - `configure_logging(level, format, file)` 全局幂等配置入口
  - 三个 env vars：`CIA_LOG_LEVEL` / `CIA_LOG_FORMAT` / `CIA_LOG_FILE`
- 替换全部 30 处 `print(stderr)`：
  - `runtime/web_tools.py` 12 处 → `logger.warning` / `logger.debug`
  - `runtime/model_runtime.py` 1 处（FakeModelProvider warning）
  - `agents/collector.py` 5 处 → `logger.info`（saved sources、skip url）
    / `logger.warning`（model fallback）
  - `agents/analyst.py` 4 处 → `logger.warning`（fallback）
    / `logger.error`（call failed、validation failed）
  - `agents/writer.py` 6 处（同 analyst 模式）
  - 删除三个 agent 文件里 `import sys as _sys` 的死代码
- CLI / web 入口加 `configure_logging()` 调用
- 7 个新单元测试在 `tests/unit/test_logging.py`
- `runtime/__init__.py` 已经导出 `TokenBucket`（[[36-rate-limiting]]），
  `logging` 不需要从 `runtime/__init__.py` 导出（自己一个模块）

Out of scope:

- 切换到 `structlog` / `python-json-logger` 等第三方库（需求窄，
  自实现 ~200 行够用）
- 把 `print(stdout)`（CLI 给用户的真实输出）改成 logger（这些是
  正常的 user-facing 输出，不是 log）
- `BaseHTTPRequestHandler.log_message = pass` 不动（已经在
  `web/__init__.py:861` 抑制 default stderr noise）
- 多线程 / 异步 logging（`logging` 模块本身线程安全，无并发写入
  问题）

## Design

### 模块结构

```
competitive_intel_agents/logging.py
  ├── get_logger(name) -> logging.Logger
  ├── get_run_logger(name, run_id=, agent=, round=, **extra) -> LoggerAdapter
  ├── _ContextAdapter(LoggerAdapter)        # merge bound + caller extras
  ├── JsonFormatter(logging.Formatter)      # one JSON object per line
  ├── TextFormatter(logging.Formatter)      # human readable LEVEL ts logger | msg | k=v
  └── configure_logging(level, format, file) -> None    # idempotent
```

### Idempotent 配置

```python
def configure_logging(...):
    # Resolution: arg > env > default
    ...
    root = logging.getLogger("competitive_intel_agents")
    # 清掉 _cia_owned 的 handler；用户自己装的 handler 不动
    for h in list(root.handlers):
        if getattr(h, "_cia_owned", False):
            root.removeHandler(h)
    handler = ...
    handler._cia_owned = True
    root.addHandler(handler)
```

二次调用替换 formatter / level，**不**叠 handler。CLI 进程每次启动
调一次；测试 fixture 也可以反复调切换 format。

### Adapter 模式注入 run context

Python 自带 `logging.LoggerAdapter` 的 `process()` 默认行为是
**REPLACE** kwargs['extra']，不是 merge。所以如果 caller 在
`logger.info(msg, extra={"url": ...})` 里传了 `extra`，bind 进去的
`run_id` / `agent` / `round` 就丢了。

`_ContextAdapter` 重写 `process` 做 merge：

```python
def process(self, msg, kwargs):
    merged = dict(self.extra)
    if isinstance(kwargs.get("extra"), Mapping):
        merged.update(kwargs["extra"])
    kwargs["extra"] = merged
    return msg, kwargs
```

## Tests

`tests/unit/test_logging.py`（7 个）：

1. `test_get_logger_returns_namespaced_child_logger` — name 自动锚到
   project 命名空间下
2. `test_json_formatter_emits_required_fields` — ts/level/logger/msg
   + extras 全部出现
3. `test_text_formatter_appends_extra_as_kv` — extras 按 alpha 排序
   附加到尾部
4. `test_configure_logging_is_idempotent` — 两次调用 handler 数恒为 1
5. `test_run_logger_injects_context_into_extras` — adapter 注入的
   run_id 跟 caller 自带的 extras 都出现在 record
6. `test_configure_logging_swaps_formatter_when_called_twice` —
   format 切换无 handler 堆积
7. `test_configure_logging_reads_env_vars` — 三个 env 都生效

## Backward compatibility

- `print(stdout)` 不动 — CLI / dashboard 给用户看的输出
- 旧测试不依赖 stderr 内容（grep 过 `tests/`），替换不引起回归
- `configure_logging()` 默认行为（不传参 + 无 env）= INFO + text +
  stderr，跟之前 `print(stderr)` 的视觉效果差不多，开发者看不到
  显著变化

## Related

- [[36-rate-limiting]] — `penalize` 事件可以借 logger.warning 上报；
  本模块的 logger 也是限速器异常的统一出口
- [[33-global-timeout]] — timeout 触发的 caveat 当前是 ReviewFeedback；
  如果未来想加遥测，logger 是顺势加的入口
- [[39-deployment]] — Docker 镜像默认 `CIA_LOG_FORMAT=json`，让线上
  日志直接是结构化的 JSON Lines
