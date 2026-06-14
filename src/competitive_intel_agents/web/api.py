"""JSON REST API surface under ``/api/`` — programmatic access to runs.

The dashboard already serves HTML at ``/``, ``/runs/...``, ``/workflow``, etc.
This module reuses the same ``BaseHTTPRequestHandler`` plumbing but emits
``application/json`` and accepts JSON bodies. It intentionally stays
stdlib-only to match the rest of the project.

Auth model:
    The env var ``CIA_API_TOKEN`` controls Bearer Token auth.

    - Unset / empty: every request is accepted. This preserves the
      "open localhost dashboard" PoC ergonomics so existing scripts and
      browser bookmarks keep working with ``/api/`` too.
    - Set: every ``/api/`` request must carry
      ``Authorization: Bearer <token>``. Mismatched / missing → 401.

    Auth is enforced uniformly on every ``/api/`` route, including GETs,
    because read access to claims and sources is also confidential.

Response envelope:
    ``{"data": <payload>, "error": null}`` on success, with ``data``
    being whatever the route returns.

    ``{"data": null, "error": {"code": "...", "message": "..."}}`` on
    failure. ``code`` is a stable string (``not_found``, ``unauthorized``,
    ``bad_request``, ``method_not_allowed``, ``internal``) so clients can
    branch on it without parsing prose. ``message`` is human readable.

Run creation is asynchronous: ``POST /api/runs`` validates the body,
spawns a background thread (same machinery as the HTML form path), and
returns ``202 Accepted`` immediately with the run_id. Clients then poll
``GET /api/runs/{id}`` until ``status`` is no longer ``running``.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, unquote, urlparse

from competitive_intel_agents.logging import get_logger
from competitive_intel_agents.models import CompetitiveIntelRequest

if TYPE_CHECKING:
    from competitive_intel_agents.workspace import LocalWorkspace


logger = get_logger(__name__)


_API_PREFIX = "/api/"

_VALID_METHODS = frozenset({"GET", "POST"})


def is_api_path(path: str) -> bool:
    """Return True if *path* (just the path portion, no query) is in /api/ space."""
    return path == "/api" or path.startswith(_API_PREFIX)


def handle_api_request(
    handler: BaseHTTPRequestHandler,
    method: str,
    workspace: "LocalWorkspace",
) -> None:
    """Dispatch an ``/api/*`` request and write a JSON response.

    The caller (``WebDashboardHandler.do_GET`` / ``do_POST``) already
    decided this is an API request; this function takes over the entire
    response cycle and returns nothing.
    """
    parsed = urlparse(handler.path)
    path = parsed.path

    if not _check_auth(handler):
        _write_error(handler, 401, "unauthorized", "missing or invalid bearer token")
        return

    try:
        if method == "POST" and path == "/api/runs":
            _handle_post_runs(handler, workspace)
            return
        if method == "GET" and path == "/api/runs":
            _handle_list_runs(handler, workspace, parsed.query)
            return
        if method == "GET" and path.startswith("/api/runs/"):
            _handle_run_subroute(handler, workspace, path)
            return
        if method not in _VALID_METHODS:
            _write_error(handler, 405, "method_not_allowed", f"method {method} not supported")
            return
        _write_error(handler, 404, "not_found", f"unknown api route: {path}")
    except _ApiError as exc:
        _write_error(handler, exc.status, exc.code, exc.message)
    except Exception as exc:
        # Last-resort safety net so a buggy handler never crashes the
        # whole server thread. The exception is also logged so operators
        # can investigate offline.
        logger.exception(
            "api handler crashed",
            extra={"path": path, "method": method},
        )
        _write_error(handler, 500, "internal", str(exc))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _handle_post_runs(handler: BaseHTTPRequestHandler, workspace: "LocalWorkspace") -> None:
    body = _read_json_body(handler)
    if not isinstance(body, dict):
        raise _ApiError(400, "bad_request", "request body must be a JSON object")

    company = _str_field(body, "company", required=True)
    market = _str_field(body, "market", required=False) or None
    competitors = _str_list(body, "competitors")
    questions = _str_list(body, "questions")
    real_web = bool(body.get("real_web", False))
    real_model = bool(body.get("real_model", False))

    try:
        request = CompetitiveIntelRequest(
            company=company,
            market=market,
            competitors=competitors,
            questions=questions,
        )
    except (TypeError, ValueError) as exc:
        raise _ApiError(400, "bad_request", str(exc)) from exc

    # Import lazily so test injection works — tests stub start_run_from_form
    # to avoid spawning a background thread.
    from competitive_intel_agents.web import create_run_from_form, start_run_from_form

    form = _request_to_form_payload(request, real_web=real_web, real_model=real_model)
    if real_web or real_model:
        result = start_run_from_form(workspace, form)
        status_code = 202
    else:
        # Fully fake pipeline finishes synchronously and is cheap enough
        # to inline; this is the "smoke-test" path for CI / dev.
        result = create_run_from_form(workspace, form)
        status_code = 201

    payload = {
        "run_id": result.run_id,
        "status": result.status,
    }
    _write_json(handler, status_code, {"data": payload, "error": None})


def _handle_list_runs(
    handler: BaseHTTPRequestHandler,
    workspace: "LocalWorkspace",
    raw_query: str,
) -> None:
    query = parse_qs(raw_query)
    limit = _parse_int(query, "limit", default=20, minimum=1, maximum=200)
    offset = _parse_int(query, "offset", default=0, minimum=0)

    runs = workspace.list_run_results()
    # Newest first — runs.json is appended in completion order, so we
    # reverse to surface the most recent runs at the top of the list.
    runs.reverse()
    page = runs[offset : offset + limit]
    payload = {
        "items": [_summarize_run(r) for r in page],
        "total": len(runs),
        "limit": limit,
        "offset": offset,
    }
    _write_json(handler, 200, {"data": payload, "error": None})


def _handle_run_subroute(
    handler: BaseHTTPRequestHandler,
    workspace: "LocalWorkspace",
    path: str,
) -> None:
    suffix = path[len("/api/runs/") :]
    if not suffix:
        raise _ApiError(404, "not_found", "missing run id")

    parts = [unquote(p) for p in suffix.split("/") if p]
    if not parts:
        raise _ApiError(404, "not_found", "missing run id")

    run_id = parts[0]
    rest = parts[1:]

    if not rest:
        _write_run_detail(handler, workspace, run_id)
        return

    if len(rest) == 1:
        sub = rest[0]
        if sub == "report":
            _write_report(handler, workspace, run_id)
            return
        if sub == "sources":
            _write_sources(handler, workspace, run_id)
            return
        if sub == "claims":
            _write_claims(handler, workspace, run_id)
            return
    raise _ApiError(404, "not_found", f"unknown run sub-route: {'/'.join(rest)}")


def _write_run_detail(
    handler: BaseHTTPRequestHandler,
    workspace: "LocalWorkspace",
    run_id: str,
) -> None:
    result = workspace.get_run_result(run_id)
    if result is None:
        raise _ApiError(404, "not_found", f"run not found: {run_id}")
    _write_json(handler, 200, {"data": _full_run_payload(result), "error": None})


def _write_report(
    handler: BaseHTTPRequestHandler,
    workspace: "LocalWorkspace",
    run_id: str,
) -> None:
    if workspace.get_run_result(run_id) is None:
        raise _ApiError(404, "not_found", f"run not found: {run_id}")

    accept = handler.headers.get("Accept", "") or ""
    report = workspace.artifacts.get_latest_report(run_id)

    if "text/markdown" in accept and report is not None:
        body = _render_report_markdown(report).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/markdown; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return

    if report is None:
        # Run is still pending writer (or aborted before writer).
        # 200 with null payload is the right shape — the run exists, the
        # report does not yet, and clients can poll.
        _write_json(handler, 200, {"data": None, "error": None})
        return

    payload = {
        "id": report.id,
        "run_id": report.run_id,
        "version": report.version,
        "status": report.status,
        "sections": report.sections,
        "claim_ids": list(report.claim_ids),
        "source_ids": list(report.source_ids),
    }
    _write_json(handler, 200, {"data": payload, "error": None})


def _write_sources(
    handler: BaseHTTPRequestHandler,
    workspace: "LocalWorkspace",
    run_id: str,
) -> None:
    if workspace.get_run_result(run_id) is None:
        raise _ApiError(404, "not_found", f"run not found: {run_id}")

    sources = workspace.artifacts.list_sources(run_id)
    payload = {
        "items": [
            {
                "id": s.id,
                "url": s.url,
                "title": s.title,
                "snippet": s.snippet,
                "source_type": s.source_type,
                "retrieved_at": s.retrieved_at,
                "metadata": dict(s.metadata),
            }
            for s in sources
        ],
        "total": len(sources),
    }
    _write_json(handler, 200, {"data": payload, "error": None})


def _write_claims(
    handler: BaseHTTPRequestHandler,
    workspace: "LocalWorkspace",
    run_id: str,
) -> None:
    if workspace.get_run_result(run_id) is None:
        raise _ApiError(404, "not_found", f"run not found: {run_id}")

    claims = workspace.artifacts.list_claims(run_id)
    payload = {
        "items": [
            {
                "id": c.id,
                "text": c.text,
                "confidence": c.confidence,
                # accuracy was added by [[35-claim-source-cross-check]]; expose
                # it so API clients can act on it without scraping HTML.
                "accuracy": c.accuracy,
                "reasoning": c.reasoning,
                "source_ids": list(c.source_ids),
                "version": c.version,
            }
            for c in claims
        ],
        "total": len(claims),
    }
    _write_json(handler, 200, {"data": payload, "error": None})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ApiError(Exception):
    """Internal — raised inside route handlers to short-circuit to a JSON error."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _check_auth(handler: BaseHTTPRequestHandler) -> bool:
    expected = os.environ.get("CIA_API_TOKEN", "").strip()
    if not expected:
        return True  # auth disabled — local PoC mode
    header = handler.headers.get("Authorization", "") or ""
    if not header.lower().startswith("bearer "):
        return False
    presented = header[len("bearer ") :].strip()
    return presented == expected


def _read_json_body(handler: BaseHTTPRequestHandler) -> Any:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _ApiError(400, "bad_request", f"invalid JSON body: {exc}") from exc


def _str_field(body: dict, key: str, *, required: bool) -> str:
    value = body.get(key, "")
    if not isinstance(value, str):
        raise _ApiError(400, "bad_request", f"field {key!r} must be a string")
    value = value.strip()
    if required and not value:
        raise _ApiError(400, "bad_request", f"field {key!r} is required")
    return value


def _str_list(body: dict, key: str) -> list[str]:
    value = body.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise _ApiError(400, "bad_request", f"field {key!r} must be an array of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise _ApiError(400, "bad_request", f"field {key!r} must be an array of strings")
        item = item.strip()
        if item:
            out.append(item)
    return out


def _parse_int(query: dict[str, list[str]], key: str, *, default: int, minimum: int, maximum: int | None = None) -> int:
    raw = query.get(key, [None])[0]
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise _ApiError(400, "bad_request", f"query param {key!r} must be an integer") from exc
    if value < minimum:
        raise _ApiError(400, "bad_request", f"query param {key!r} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise _ApiError(400, "bad_request", f"query param {key!r} must be <= {maximum}")
    return value


def _request_to_form_payload(
    request: CompetitiveIntelRequest,
    *,
    real_web: bool,
    real_model: bool,
) -> dict[str, list[str]]:
    """Adapt a CompetitiveIntelRequest into the form-shaped dict that
    ``create_run_from_form`` / ``start_run_from_form`` expect.

    Keeping the form path as the single execution entrypoint avoids a
    second copy of orchestrator wiring in this file."""
    form: dict[str, list[str]] = {
        "company": [request.company],
        "market": [request.market or ""],
        "competitors": [", ".join(request.competitors)],
        "questions": [", ".join(request.questions)],
    }
    if real_web:
        form["real_web"] = ["1"]
    if real_model:
        form["real_model"] = ["1"]
    return form


def _summarize_run(result) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "report_id": result.report_id,
        "review_feedback_count": len(result.review_feedback or []),
        "caveats_count": len(getattr(result, "caveats", []) or []),
        "error": result.error,
    }


def _full_run_payload(result) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "report_id": result.report_id,
        "review_feedback": [item.to_dict() for item in (result.review_feedback or [])],
        "caveats": [item.to_dict() for item in (getattr(result, "caveats", []) or [])],
        "error": result.error,
    }


def _render_report_markdown(report) -> str:
    """Lightweight markdown rendering — same shape as the export module
    but inlined here so the API does not depend on the optional export
    layer's precise contract."""
    lines = [f"# Report {report.id}", ""]
    for section, content in report.sections.items():
        lines.append(f"## {section}")
        lines.append("")
        lines.append(content)
        lines.append("")
    return "\n".join(lines)


def _write_json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _write_error(
    handler: BaseHTTPRequestHandler,
    status: int,
    code: str,
    message: str,
) -> None:
    _write_json(
        handler,
        status,
        {"data": None, "error": {"code": code, "message": message}},
    )


__all__ = [
    "is_api_path",
    "handle_api_request",
]
