"""Integration tests for the JSON REST API surface (web/api.py).

These tests boot a real ``ThreadingHTTPServer`` on an ephemeral port and
issue HTTP requests through stdlib ``http.client`` so the entire
``WebDashboardHandler`` → ``handle_api_request`` path is exercised.
"""

from __future__ import annotations

import json
import os
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from tempfile import TemporaryDirectory
from threading import Thread

import pytest

from competitive_intel_agents.models import (
    AnalysisClaim,
    ReportDraft,
    ReviewFeedback,
    RunResult,
    SourceArtifact,
)
from competitive_intel_agents.web import WebDashboardHandler
from competitive_intel_agents.workspace import LocalWorkspace


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server():
    """Spin up a real WebDashboardHandler-backed HTTP server on a random port."""
    with TemporaryDirectory() as tmpdir:
        workspace = LocalWorkspace(tmpdir)
        WebDashboardHandler.workspace = workspace
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), WebDashboardHandler)
        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield httpd, workspace
        finally:
            httpd.shutdown()
            thread.join(timeout=2)


def _request(httpd, method: str, path: str, *, body=None, headers=None):
    conn = HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    raw = None
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        headers = {**(headers or {}), "Content-Type": "application/json"}
        headers.setdefault("Content-Length", str(len(raw)))
    conn.request(method, path, body=raw, headers=headers or {})
    response = conn.getresponse()
    payload = response.read()
    return response, payload


def _populate_run(workspace: LocalWorkspace, run_id: str = "run_api_001") -> None:
    workspace.save_run_result(
        RunResult(
            run_id=run_id,
            status="completed",
            report_id="report_api1",
            review_feedback=[
                ReviewFeedback(
                    issue="weak_inference",
                    target_agent="analyst",
                    target_artifact_id="claim_api1",
                    message="More evidence needed.",
                    required_action="add_evidence",
                ),
            ],
            caveats=[
                ReviewFeedback(
                    issue="missing_source",
                    target_agent="collector",
                    target_artifact_id="-",
                    message="No source for pricing.",
                    required_action="collect_pricing",
                    blocking=False,
                ),
            ],
        )
    )
    workspace.artifacts.save_source(
        SourceArtifact(
            id="src_api1",
            run_id=run_id,
            url="https://example.com/p",
            title="Pricing Page",
            snippet="Public pricing.",
            metadata={"char_count": 1024},
        )
    )
    workspace.artifacts.save_claim(
        AnalysisClaim(
            id="claim_api1",
            run_id=run_id,
            text="Competitor cut prices.",
            source_ids=["src_api1"],
            confidence="high",
            reasoning="Public page diff.",
            accuracy="supported",
        )
    )
    workspace.artifacts.save_report(
        ReportDraft(
            id="report_api1",
            run_id=run_id,
            sections={"Overview": "Pricing went down."},
            claim_ids=["claim_api1"],
            source_ids=["src_api1"],
        )
    )


# ---------------------------------------------------------------------------
# POST /api/runs
# ---------------------------------------------------------------------------


def test_post_runs_creates_run_and_returns_201_for_fake_pipeline(server):
    httpd, workspace = server
    response, payload = _request(
        httpd,
        "POST",
        "/api/runs",
        body={
            "company": "Notion",
            "market": "productivity",
            "competitors": ["Coda"],
            "questions": ["pricing"],
        },
    )

    # Fake pipeline (no real_web / real_model) finishes synchronously:
    # 201 with the final status, not 202.
    assert response.status == 201
    parsed = json.loads(payload)
    assert parsed["error"] is None
    assert parsed["data"]["run_id"].startswith("run_")
    assert parsed["data"]["status"] in {
        "approved",
        "approved_with_caveats",
        "completed",
        "needs_more_evidence",
        "rework_failed",
    }
    assert len(workspace.list_run_results()) == 1


def test_post_runs_accepts_real_flags_and_returns_202(server, monkeypatch):
    httpd, workspace = server

    # Stub the background-thread launcher so we don't actually run a live
    # collector. The API contract is "202 + run_id"; the orchestration is
    # tested elsewhere.
    captured = {}

    def fake_start(workspace, form):
        from competitive_intel_agents.models import RunResult as RR

        result = RR(run_id="run_api_async", status="running")
        workspace.save_run_result(result)
        captured["form"] = form
        return result

    monkeypatch.setattr("competitive_intel_agents.web.api.start_run_from_form", fake_start, raising=False)
    # The API imports lazily inside the handler, so patch the module the
    # handler will resolve to as well.
    import competitive_intel_agents.web as web_mod

    monkeypatch.setattr(web_mod, "start_run_from_form", fake_start, raising=False)

    response, payload = _request(
        httpd,
        "POST",
        "/api/runs",
        body={
            "company": "Notion",
            "market": "productivity",
            "competitors": ["Coda"],
            "questions": ["pricing"],
            "real_web": True,
            "real_model": True,
        },
    )

    assert response.status == 202
    parsed = json.loads(payload)
    assert parsed["data"]["run_id"] == "run_api_async"
    assert parsed["data"]["status"] == "running"
    assert captured["form"]["company"] == ["Notion"]
    assert captured["form"].get("real_web") == ["1"]
    assert captured["form"].get("real_model") == ["1"]


def test_post_runs_rejects_missing_company_with_400(server):
    httpd, _ = server
    response, payload = _request(
        httpd,
        "POST",
        "/api/runs",
        body={"market": "productivity"},
    )

    assert response.status == 400
    parsed = json.loads(payload)
    assert parsed["data"] is None
    assert parsed["error"]["code"] == "bad_request"
    assert "company" in parsed["error"]["message"]


def test_post_runs_rejects_invalid_json_body_with_400(server):
    httpd, _ = server
    conn = HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    conn.request(
        "POST",
        "/api/runs",
        body=b"{not json",
        headers={"Content-Type": "application/json", "Content-Length": "9"},
    )
    response = conn.getresponse()
    parsed = json.loads(response.read())
    assert response.status == 400
    assert parsed["error"]["code"] == "bad_request"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_post_runs_requires_bearer_token_when_env_set(server, monkeypatch):
    httpd, _ = server
    monkeypatch.setenv("CIA_API_TOKEN", "secret123")

    # No auth header → 401
    response, payload = _request(
        httpd,
        "POST",
        "/api/runs",
        body={"company": "X"},
    )
    assert response.status == 401
    assert json.loads(payload)["error"]["code"] == "unauthorized"

    # Wrong token → 401
    response, payload = _request(
        httpd,
        "POST",
        "/api/runs",
        body={"company": "X"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status == 401

    # Correct token → 201 (fake pipeline path)
    response, payload = _request(
        httpd,
        "POST",
        "/api/runs",
        body={"company": "X"},
        headers={"Authorization": "Bearer secret123"},
    )
    assert response.status == 201


def test_auth_skipped_when_token_unset(server, monkeypatch):
    httpd, _ = server
    monkeypatch.delenv("CIA_API_TOKEN", raising=False)
    response, _ = _request(httpd, "GET", "/api/runs")
    assert response.status == 200


def test_auth_applies_to_get_routes(server, monkeypatch):
    httpd, _ = server
    monkeypatch.setenv("CIA_API_TOKEN", "secret123")

    response, _ = _request(httpd, "GET", "/api/runs")
    assert response.status == 401


# ---------------------------------------------------------------------------
# GET /api/runs and /api/runs/{id}
# ---------------------------------------------------------------------------


def test_get_runs_returns_paginated_list(server):
    httpd, workspace = server
    for i in range(3):
        workspace.save_run_result(
            RunResult(run_id=f"run_{i:03d}", status="completed", report_id=None)
        )

    response, payload = _request(httpd, "GET", "/api/runs?limit=2&offset=0")
    assert response.status == 200
    parsed = json.loads(payload)
    assert parsed["data"]["total"] == 3
    assert parsed["data"]["limit"] == 2
    assert parsed["data"]["offset"] == 0
    assert len(parsed["data"]["items"]) == 2

    # Newest-first ordering: the most recently saved run is first.
    assert parsed["data"]["items"][0]["run_id"] == "run_002"

    response, payload = _request(httpd, "GET", "/api/runs?limit=2&offset=2")
    parsed = json.loads(payload)
    assert len(parsed["data"]["items"]) == 1


def test_get_run_detail_returns_full_state(server):
    httpd, workspace = server
    _populate_run(workspace)

    response, payload = _request(httpd, "GET", "/api/runs/run_api_001")
    assert response.status == 200
    parsed = json.loads(payload)
    data = parsed["data"]
    assert data["run_id"] == "run_api_001"
    assert data["status"] == "completed"
    assert data["report_id"] == "report_api1"
    assert len(data["review_feedback"]) == 1
    assert len(data["caveats"]) == 1
    assert data["caveats"][0]["issue"] == "missing_source"


def test_unknown_run_returns_404(server):
    httpd, _ = server
    response, payload = _request(httpd, "GET", "/api/runs/run_does_not_exist")
    assert response.status == 404
    parsed = json.loads(payload)
    assert parsed["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# Sub-resources
# ---------------------------------------------------------------------------


def test_get_sources_returns_artifact_list(server):
    httpd, workspace = server
    _populate_run(workspace)

    response, payload = _request(httpd, "GET", "/api/runs/run_api_001/sources")
    assert response.status == 200
    parsed = json.loads(payload)
    assert parsed["data"]["total"] == 1
    assert parsed["data"]["items"][0]["id"] == "src_api1"
    assert parsed["data"]["items"][0]["url"] == "https://example.com/p"


def test_get_claims_includes_accuracy_field(server):
    httpd, workspace = server
    _populate_run(workspace)

    response, payload = _request(httpd, "GET", "/api/runs/run_api_001/claims")
    assert response.status == 200
    parsed = json.loads(payload)
    items = parsed["data"]["items"]
    assert items[0]["id"] == "claim_api1"
    assert items[0]["accuracy"] == "supported"
    assert items[0]["confidence"] == "high"


def test_get_report_returns_json_by_default(server):
    httpd, workspace = server
    _populate_run(workspace)

    response, payload = _request(httpd, "GET", "/api/runs/run_api_001/report")
    assert response.status == 200
    assert "application/json" in response.getheader("Content-Type", "")
    parsed = json.loads(payload)
    assert parsed["data"]["id"] == "report_api1"
    assert parsed["data"]["sections"]["Overview"] == "Pricing went down."


def test_get_report_negotiates_markdown(server):
    httpd, workspace = server
    _populate_run(workspace)

    response, payload = _request(
        httpd,
        "GET",
        "/api/runs/run_api_001/report",
        headers={"Accept": "text/markdown"},
    )
    assert response.status == 200
    assert "text/markdown" in response.getheader("Content-Type", "")
    body = payload.decode("utf-8")
    assert "# Report report_api1" in body
    assert "## Overview" in body
    assert "Pricing went down." in body


# ---------------------------------------------------------------------------
# Method handling
# ---------------------------------------------------------------------------


def test_unknown_api_route_returns_404(server):
    httpd, _ = server
    response, payload = _request(httpd, "GET", "/api/garbage")
    assert response.status == 404
    parsed = json.loads(payload)
    assert parsed["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# Security / robustness — added per PR #24 review (B1, B2, M1, M3)
# ---------------------------------------------------------------------------


def test_whitespace_only_token_fails_closed(server, monkeypatch):
    """B2: a misconfigured ``CIA_API_TOKEN`` (only whitespace) must NOT
    silently disable auth. The whole point of setting the env var is to
    gate access; treating ``"   "`` as ``unset`` would be a configuration
    trapdoor."""
    httpd, _ = server
    monkeypatch.setenv("CIA_API_TOKEN", "   ")

    response, payload = _request(httpd, "GET", "/api/runs")
    assert response.status == 401
    parsed = json.loads(payload)
    assert parsed["error"]["code"] == "unauthorized"


def test_internal_error_does_not_echo_exception_string(server, monkeypatch):
    """M1: a 500 response must not expose the raw exception message to
    the caller. SQLite errors, provider URLs and similar internals can
    end up there. Only a correlation id should leak; details go to the
    structured logger so operators can correlate offline."""
    httpd, workspace = server

    def _boom():
        raise RuntimeError("INTERNAL_PATH=/var/lib/secret/db.sqlite TOKEN=xyz")

    monkeypatch.setattr(workspace, "list_run_results", _boom, raising=False)

    response, payload = _request(httpd, "GET", "/api/runs")
    assert response.status == 500
    parsed = json.loads(payload)
    assert parsed["error"]["code"] == "internal"
    assert "/var/lib/secret/db.sqlite" not in parsed["error"]["message"]
    assert "TOKEN=xyz" not in parsed["error"]["message"]
    assert "correlation_id=" in parsed["error"]["message"]


def test_oversized_request_body_rejected_with_413(server):
    """M3: an unbounded ``Content-Length`` is a trivial DoS / OOM vector.
    The API must refuse anything over the 1 MiB ceiling before reading
    a single byte off the wire."""
    httpd, _ = server
    conn = HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    conn.request(
        "POST",
        "/api/runs",
        body=b"",
        # 10 MiB declared in the header — server should refuse without
        # reading the body.
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(10 * 1024 * 1024),
        },
    )
    response = conn.getresponse()
    payload = response.read()
    assert response.status == 413
    parsed = json.loads(payload)
    assert parsed["error"]["code"] == "payload_too_large"


def test_malformed_content_length_returns_400(server):
    """M3: a non-numeric ``Content-Length`` must produce a clean 400,
    not crash through the bare exception net."""
    httpd, _ = server
    conn = HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    # Bypass HTTPConnection's automatic Content-Length to send garbage.
    conn.putrequest("POST", "/api/runs", skip_host=False)
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", "not-a-number")
    conn.endheaders()
    response = conn.getresponse()
    payload = response.read()
    assert response.status == 400
    parsed = json.loads(payload)
    assert parsed["error"]["code"] == "bad_request"
    assert "Content-Length" in parsed["error"]["message"]


def test_token_compare_is_constant_time(monkeypatch):
    """B1: the auth check must use ``secrets.compare_digest`` so the
    side-channel on shared-prefix length is closed. We verify the
    code path actually goes through ``compare_digest`` rather than
    plain ``==``."""
    import competitive_intel_agents.web.api as api_module

    monkeypatch.setenv("CIA_API_TOKEN", "abc123")

    calls = []
    real = api_module.secrets.compare_digest

    def _spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(api_module.secrets, "compare_digest", _spy)

    class _FakeHandler:
        path = "/api/runs"
        headers = {"Authorization": "Bearer wrong"}

    assert api_module._check_auth(_FakeHandler()) is False
    assert calls, "compare_digest should be the comparison primitive"
    assert calls[0] == (b"wrong", b"abc123")
