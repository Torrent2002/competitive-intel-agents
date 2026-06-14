# 学习文档 37：结构化日志

## 一句话概括

**`print(file=sys.stderr)` → `logging.Logger` 体系**：每条日志带 `run_id` / `agent` / `round` 结构化字段，可切 text / JSON 两种格式，level 可过滤，可重定向到文件，**全部用 Python 标准库实现**，零新依赖。

## 为什么需要它

### 触发改动的真实场景

`run_3dc810266d52` 出问题时，日志长这样（mixed format，没结构）：

```
[ddg] query='飞书 协作' results=0 error=...
[bing] query='飞书 协作' results=0 error=HTTP 429
[collector] saved 2 sources, total=2 (target=2)
[writer] WARNING: model failed, falling back to template report
[analyst] validation failed: 'source_assessments' not in dict_keys([...])
```

要回答"哪几个 run 出现过 model fallback"必须 grep + 人眼解析，因为：
- 没有 `run_id` 字段 — 多个 run 并发时根本分不开
- 没有 level — `[writer] WARNING:` 是字符串，不是 log level，过滤不了
- 格式不统一 — 有的 `key=value`，有的 `f-string`，有的 `[tag]:` 嵌
- 不能输出 JSON — 接日志聚合系统（Loki / Datadog / ELK）只能再写解析

### 为什么不直接上 structlog

考虑过：
1. `structlog` — 功能丰富但概念多（contextvars、wrap_logger、cls 配置）
2. `python-json-logger` — 简单但纯 JSON formatter，没有 contextvar 注入
3. 自实现 — `logging.Logger` + `LoggerAdapter` + 60 行自定义 formatter

最终选 #3，原因：
- 项目目前 0 第三方依赖（除 curl_cffi，commit df24623 后），加 structlog 会破坏"single binary worth of code" 的简洁
- 需求窄：只要 JSON / text 两种格式 + run_id 注入。structlog 90% 功能用不到
- `LoggerAdapter` 已经能解决"绑死 contextvar"的需求，不需要 structlog 的 `bound logger` 抽象

但 `LoggerAdapter` 默认行为有个坑：

### LoggerAdapter merge 行为陷阱

Python 内置 `LoggerAdapter.process()` 是这样的：

```python
def process(self, msg, kwargs):
    kwargs["extra"] = self.extra   # ← REPLACE，不是 merge
    return msg, kwargs
```

意思是：如果 caller 在 `logger.info(msg, extra={"url": "..."})` 里自己传了 `extra`，**绑定的 `run_id` / `agent` 全没了**。这跟 caller 直觉相反 — 大家都以为 adapter 是 "拼接" 行为。

所以必须重写：

```python
class _ContextAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        merged = dict(self.extra)
        if isinstance(kwargs.get("extra"), Mapping):
            merged.update(kwargs["extra"])
        kwargs["extra"] = merged
        return msg, kwargs
```

合并 bound context + caller extras，缺一不可。

## 关键代码

### 1. JsonFormatter

```python
class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(_record_extras(record))   # 抽出 record.__dict__ 里非标准的字段
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
```

`_record_extras` 关键：从 `LogRecord.__dict__` 里抠出 `_RESERVED_RECORD_KEYS` 之外的所有 key，这就是 `extra={...}` 传进来的字段。

### 2. configure_logging idempotent

```python
def configure_logging(level=None, format=None, file=None):
    resolved_level = (level or os.environ.get("CIA_LOG_LEVEL") or "INFO").upper()
    resolved_format = (format or os.environ.get("CIA_LOG_FORMAT") or "text").lower()
    resolved_file = file if file is not None else os.environ.get("CIA_LOG_FILE")
    
    root = logging.getLogger("competitive_intel_agents")
    root.setLevel(getattr(logging, resolved_level, logging.INFO))
    root.propagate = False
    
    # 关键：只移除自己 own 的 handler
    for h in list(root.handlers):
        if getattr(h, "_cia_owned", False):
            root.removeHandler(h)
    
    handler = logging.FileHandler(resolved_file) if resolved_file else logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if resolved_format == "json" else TextFormatter())
    handler._cia_owned = True
    root.addHandler(handler)
```

`_cia_owned` flag 是关键 — 用户自己装的 handler 不动，只清自己的。这样 fixture 里反复 `configure_logging()` 不会污染 root logger。

### 3. agent 中的接入

```python
# agents/writer.py 顶部
from competitive_intel_agents.logging import get_logger
logger = get_logger(__name__)

# 调用点
logger.warning(
    "model failed, falling back to template report",
    extra={"run_id": context.run_id, "agent": "writer"},
)
```

或者用 `get_run_logger` 把 context 绑死：

```python
rlog = get_run_logger(__name__, run_id=context.run_id, agent="writer", round=n)
rlog.info("saved sections", extra={"sections": list(sections.keys())})
```

后者好处：每条 log 都自动带上 run context，不用 caller 手动重复。当前 4 个 agent 改造**只用了 `get_logger` + 手动 extras**，因为 `run_round` 之外（如 `_model_sections`、`_filter_and_save`）也要打日志，把 adapter 传穿不划算。等 [[39-deployment]] 上 JSON 格式时再考虑 adapter 化。

## 设计取舍

### 为什么 ts 不用毫秒精度

JSON line 一行一个 record，毫秒精度（`%H:%M:%S.%f`）会让大多数 record 被 `.123456` 后缀拉长。日志聚合系统几乎都按秒索引，毫秒级别用不上。

### 为什么 collector "saved sources" 是 INFO 不是 DEBUG

观察：用户跑 web dashboard 时点 "Real web tools"，预期看到进度反馈。
- DEBUG → 用户看不到，只是开发自己在 debug 时打开
- INFO → 默认打印，用户看得到 "saved 3 sources, total=3" 表明 collector 在干活
- WARNING → 提升到这里读者会以为出问题了

INFO 是 "正常进度报告" 的标准位置。collector 的 retry / fallback 才升级到 WARNING。

### 为什么 analyst / writer 的 model failure 是 ERROR

跟 collector 的 fallback 区分：
- collector 的 fallback（algorithmic scoring）是**完整功能**的退化版，user 看不出区别 → WARNING（"出了问题但救回来了"）
- analyst / writer 的 model failure 退化成 template，**user 一眼能看出报告变弱了**（template 没法生成有深度的 SWOT）→ ERROR（"出了问题且影响交付质量"）

logger level 不光是 "严重程度" 的同义词，也是 "对外用户可观测后果" 的反映。

### 为什么不全部走 LoggerAdapter

我刚才用的是 `logger.warning(msg, extra={"run_id": ...})` 显式传 extras，没用 `get_run_logger`。理由：

每个 agent 内部有 `run_round`、`_model_sections`、`_filter_and_save` 三层方法。要让所有层都用同一个 adapter，要么：
1. `run_round` 创建 adapter 然后传给所有内部方法（参数污染）
2. 用 contextvars / threading.local（state mgmt 复杂）

显式传 `run_id=context.run_id` 在每个 site 一行重复，但**在哪一层都能看到 context**，不需要 thread state。当前规模下这种"机械重复"成本低于全 adapter 化的复杂度。

### 为什么不删 cli/__init__.py 的 print(...)

CLI 里大量 `print("Web dashboard: http://...")` 之类是给用户看的**真实输出**，不是 log。改成 logger 反而会：
1. JSON format 时把这些"用户输出"也变成 JSON，CLI 体验崩坏
2. 重定向 stderr 时把用户该看到的东西藏起来

所以严格分：
- **输出（stdout）**：给人看，用 `print`
- **日志（stderr or file）**：给机器解析，用 `logger`

## 测试

`tests/unit/test_logging.py` 7 个：

1. `test_get_logger_returns_namespaced_child_logger` — `get_logger("collector")` 自动变 `competitive_intel_agents.collector`
2. `test_json_formatter_emits_required_fields` — ts/level/logger/msg + extras 都在
3. `test_text_formatter_appends_extra_as_kv` — k=v 按 alpha 排序
4. `test_configure_logging_is_idempotent` — 两次调用 handler 数仍为 1
5. `test_run_logger_injects_context_into_extras` — adapter merge 行为正确
6. `test_configure_logging_swaps_formatter_when_called_twice` — formatter 替换不堆 handler
7. `test_configure_logging_reads_env_vars` — `CIA_LOG_LEVEL` / `CIA_LOG_FORMAT` 都生效

## 面试要点

1. **`print(stderr)` 是 anti-pattern**：没 level、没结构、没 metadata。一旦项目要上线就要替换。早替换比晚替换便宜。

2. **`logging.LoggerAdapter` 的 process 默认 REPLACE 不 merge** — 实际坑。重写 `process` 才能拿到"绑定 + 调用时"的字段合并。这是经典 gotcha。

3. **JSON Lines 格式**：每行一个独立 JSON 对象，能直接 grep + jq + 灌进任何聚合系统。`json.dumps(... ensure_ascii=False)` 让中文 query 不会被 escape 成 `\uXXXX`。

4. **Idempotent configure 的 _cia_owned trick**：项目自己 own 的 handler 标记一下，重新配置时只清自己的。避免污染用户已装的 handler。

5. **不引入第三方依赖**：`structlog` 好，但 `logging.Logger` + 60 行 formatter 已经够。自评：什么时候该引依赖？答：当核心功能（contextvar inheritance、async logging、structured exception capture）确实做不到时。当前需求 0 这些。

6. **WARNING vs ERROR 的判定**：我用的是"对外用户可观测后果"作分界。collector fallback 完整 → WARNING；analyst template 让报告变弱 → ERROR。这个分法不是教科书的，是从 ops 视角倒推的。

7. **logger 不取代 print**：CLI 给用户的真实输出仍然是 `print(stdout)`。logger 是给机器解析的。混在一起会让 JSON format 模式下 CLI 体验崩坏。
