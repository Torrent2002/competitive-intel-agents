"""Unit tests for the structured logging facility."""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from competitive_intel_agents.logging import (
    JsonFormatter,
    TextFormatter,
    configure_logging,
    get_logger,
    get_run_logger,
)


@pytest.fixture(autouse=True)
def _reset_logging():
    """Each test starts from a clean root-logger state so they don't
    leak handlers into each other."""
    yield
    root = logging.getLogger("competitive_intel_agents")
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.NOTSET)
    root.propagate = True


def test_get_logger_returns_namespaced_child_logger() -> None:
    log = get_logger("competitive_intel_agents.agents.collector")
    assert log.name == "competitive_intel_agents.agents.collector"

    log_root = get_logger()
    assert log_root.name == "competitive_intel_agents"

    # Bare name auto-anchored under project root.
    log_bare = get_logger("collector")
    assert log_bare.name == "competitive_intel_agents.collector"


def test_json_formatter_emits_required_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="competitive_intel_agents.agents.collector",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="saved sources",
        args=(),
        exc_info=None,
    )
    record.run_id = "run_abc"
    record.agent = "collector"
    record.saved = 3

    line = formatter.format(record)
    payload = json.loads(line)

    # Mandatory frame fields
    assert payload["level"] == "INFO"
    assert payload["logger"] == "competitive_intel_agents.agents.collector"
    assert payload["msg"] == "saved sources"
    assert "ts" in payload
    # User-supplied structured fields
    assert payload["run_id"] == "run_abc"
    assert payload["agent"] == "collector"
    assert payload["saved"] == 3


def test_text_formatter_appends_extra_as_kv() -> None:
    formatter = TextFormatter()
    record = logging.LogRecord(
        name="competitive_intel_agents.runtime.web_tools",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="ddg returned 0 results",
        args=(),
        exc_info=None,
    )
    record.engine = "ddg"
    record.query = "acme"

    line = formatter.format(record)

    assert "WARNING" in line
    assert "ddg returned 0 results" in line
    # Sorted alphabetically
    assert "engine=ddg" in line
    assert "query=acme" in line


def test_configure_logging_is_idempotent() -> None:
    """Calling configure_logging twice must not stack handlers."""
    configure_logging(level="INFO", format="text")
    root = logging.getLogger("competitive_intel_agents")
    handler_count_first = len(root.handlers)

    configure_logging(level="INFO", format="text")
    handler_count_second = len(root.handlers)

    assert handler_count_first == handler_count_second == 1


def test_run_logger_injects_context_into_extras() -> None:
    """A LoggerAdapter from get_run_logger must carry run_id/agent/round."""
    configure_logging(level="DEBUG", format="json")

    # Capture into an in-memory stream so we can parse the JSON line.
    root = logging.getLogger("competitive_intel_agents")
    buf = StringIO()
    capture = logging.StreamHandler(buf)
    capture.setFormatter(JsonFormatter())
    capture.setLevel(logging.DEBUG)
    root.addHandler(capture)

    rlog = get_run_logger(
        "competitive_intel_agents.agents.collector",
        run_id="run_abc",
        agent="collector",
        round=2,
    )
    rlog.warning("fetched url", extra={"url": "https://example.com"})

    line = buf.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["run_id"] == "run_abc"
    assert payload["agent"] == "collector"
    assert payload["round"] == 2
    # Caller-provided extras merge — not replace — the bound context.
    assert payload["url"] == "https://example.com"


def test_configure_logging_swaps_formatter_when_called_twice() -> None:
    """Second configure_logging call should replace, not stack, formatter."""
    configure_logging(level="INFO", format="text")
    root = logging.getLogger("competitive_intel_agents")
    assert isinstance(root.handlers[0].formatter, TextFormatter)

    configure_logging(level="INFO", format="json")
    assert len(root.handlers) == 1  # still one handler
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_configure_logging_reads_env_vars(monkeypatch) -> None:
    monkeypatch.setenv("CIA_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("CIA_LOG_FORMAT", "json")
    monkeypatch.delenv("CIA_LOG_FILE", raising=False)

    configure_logging()
    root = logging.getLogger("competitive_intel_agents")
    assert root.level == logging.WARNING
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
