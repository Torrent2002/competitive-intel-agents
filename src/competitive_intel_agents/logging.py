"""Structured logging for the competitive-intel pipeline.

Purpose
-------
Replace ad-hoc ``print(file=sys.stderr)`` calls scattered across agents
and runtime adapters with a single configurable :mod:`logging`
hierarchy. Each emission carries structured fields (``run_id``,
``agent``, ``round`` …) that downstream tooling — log aggregators,
dashboards, audit pipelines — can filter on without re-parsing free
text.

Why not a third-party library
-----------------------------
We considered ``structlog`` and ``python-json-logger``. Both are
solid, but the requirements here are narrow:

* one process, no async pipeline
* JSON or human formats — no other shapes
* ``extra={...}`` already covers field injection

The ~100 lines below cover all of that without adding a dependency,
and stay within the project's "vendored standard library" style.

Configuration
-------------
Three environment variables, read once by :func:`configure_logging`:

* ``CIA_LOG_LEVEL`` — DEBUG / INFO / WARNING / ERROR (default INFO)
* ``CIA_LOG_FORMAT`` — ``text`` (default) or ``json``
* ``CIA_LOG_FILE`` — output path (default unset = stderr)

Calling :func:`configure_logging` more than once is a no-op for
handlers — idempotent so a process that has already configured
logging at the CLI entry point can be safely re-imported in tests.

Usage
-----
::

    from competitive_intel_agents.logging import get_logger, get_run_logger

    log = get_logger(__name__)
    log.warning("ddg returned 0 results", extra={"engine": "ddg", "query": q})

    # In an agent that knows its run context:
    rlog = get_run_logger(__name__, run_id=context.run_id, agent=self.name, round=n)
    rlog.info("saved sources", extra={"saved": 3, "total": 7})

The two helpers behave identically for callers that don't want to
think about the ``LoggerAdapter`` distinction; ``get_run_logger``
just preconfigures the run-scoped fields so every record carries them.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Mapping

# ── Top-level logger root ──────────────────────────────────────

_ROOT_NAME = "competitive_intel_agents"
_CONFIGURED = False  # protects against double-add of handlers


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger inside the project's namespace.

    ``name=None`` returns the root project logger; passing a module
    ``__name__`` (e.g. ``competitive_intel_agents.agents.collector``)
    returns its child logger so handlers configured at the root
    propagate down.
    """
    if not name or name == _ROOT_NAME:
        return logging.getLogger(_ROOT_NAME)
    if name.startswith(_ROOT_NAME + "."):
        return logging.getLogger(name)
    # Caller passed a non-namespaced name (e.g. just "collector").
    # Anchor it under the project root so handlers still apply.
    return logging.getLogger(f"{_ROOT_NAME}.{name}")


def get_run_logger(
    name: str | None,
    *,
    run_id: str | None = None,
    agent: str | None = None,
    round: int | None = None,
    **extra: Any,
) -> logging.LoggerAdapter:
    """Return a :class:`LoggerAdapter` that pre-injects run context.

    Every record produced via this adapter carries ``run_id``,
    ``agent``, ``round`` (and any additional ``extra`` kwargs) in its
    structured fields. Callers can still pass an ``extra`` argument at
    log-call time to add more fields per record.
    """
    base = get_logger(name)
    fields: dict[str, Any] = {}
    if run_id is not None:
        fields["run_id"] = run_id
    if agent is not None:
        fields["agent"] = agent
    if round is not None:
        fields["round"] = round
    fields.update(extra)
    return _ContextAdapter(base, fields)


class _ContextAdapter(logging.LoggerAdapter):
    """LoggerAdapter that merges its bound context with each call's
    ``extra``. The default LoggerAdapter REPLACES extras instead of
    merging — that loses the run context the moment the caller passes
    its own ``extra``, which is exactly when run context is most
    useful."""

    def process(
        self, msg: str, kwargs: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        merged: dict[str, Any] = {}
        if isinstance(self.extra, Mapping):
            merged.update(self.extra)
        caller_extra = kwargs.get("extra")
        if isinstance(caller_extra, Mapping):
            merged.update(caller_extra)
        if merged:
            kwargs["extra"] = merged
        return msg, kwargs


# ── Formatters ─────────────────────────────────────────────────

_RESERVED_RECORD_KEYS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "asctime",
    "message",
    "taskName",
}


def _record_extras(record: logging.LogRecord) -> dict[str, Any]:
    """Pluck the structured fields off a record (anything not in the
    standard LogRecord attribute set is treated as a user-provided
    ``extra`` field)."""
    return {
        k: v
        for k, v in record.__dict__.items()
        if k not in _RESERVED_RECORD_KEYS and not k.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Fields:

    * ``ts``      ISO8601 UTC timestamp (no fractional seconds — keeps
      lines compact and most log aggregators ingest cleanly)
    * ``level``   ``INFO`` / ``WARNING`` / etc.
    * ``logger``  the logger name (already namespaced under the project)
    * ``msg``     the formatted message string
    * everything from ``record.__dict__`` not in the standard set —
      this is where ``run_id``, ``agent``, ``round`` etc. land
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(_record_extras(record))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class TextFormatter(logging.Formatter):
    """Human-readable line: ``LEVEL ts logger | msg | k=v k=v``."""

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%Y-%m-%dT%H:%M:%S")
        head = f"{record.levelname:<7} {ts} {record.name} | {record.getMessage()}"
        extras = _record_extras(record)
        if extras:
            tail = " ".join(f"{k}={v}" for k, v in sorted(extras.items()))
            head = f"{head} | {tail}"
        if record.exc_info:
            head = f"{head}\n{self.formatException(record.exc_info)}"
        return head


# ── Configuration entry point ──────────────────────────────────


def configure_logging(
    level: str | None = None,
    format: str | None = None,
    file: str | None = None,
) -> None:
    """Install handlers on the project root logger.

    Resolution order for each parameter: explicit argument > env var > default.

    * ``level`` ← ``CIA_LOG_LEVEL``   default ``INFO``
    * ``format`` ← ``CIA_LOG_FORMAT``  default ``text`` (``text`` | ``json``)
    * ``file`` ← ``CIA_LOG_FILE``     default unset (use stderr)

    Idempotent: calling it more than once does not pile up handlers.
    A subsequent call with new arguments swaps the formatter / level
    in place so test fixtures can adjust the configuration mid-run.
    """
    global _CONFIGURED

    resolved_level = (level or os.environ.get("CIA_LOG_LEVEL") or "INFO").strip().upper()
    resolved_format = (format or os.environ.get("CIA_LOG_FORMAT") or "text").strip().lower()
    resolved_file = file if file is not None else os.environ.get("CIA_LOG_FILE")

    formatter: logging.Formatter
    if resolved_format == "json":
        formatter = JsonFormatter()
    else:
        formatter = TextFormatter()

    log_level = getattr(logging, resolved_level, logging.INFO)

    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(log_level)
    root.propagate = False

    # Clear existing handlers we installed so a second call doesn't
    # double-emit. Anything installed by user code is left alone.
    for h in list(root.handlers):
        if getattr(h, "_cia_owned", False):
            root.removeHandler(h)

    if resolved_file:
        handler: logging.Handler = logging.FileHandler(resolved_file, encoding="utf-8")
    else:
        handler = logging.StreamHandler()  # default: sys.stderr
    handler.setLevel(log_level)
    handler.setFormatter(formatter)
    handler._cia_owned = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    _CONFIGURED = True


__all__ = [
    "configure_logging",
    "get_logger",
    "get_run_logger",
    "JsonFormatter",
    "TextFormatter",
]
