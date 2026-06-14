"""Tests for /health and /ready endpoints exposed by the web dashboard.

These endpoints are stable entry points for container orchestrators
(Docker HEALTHCHECK, Kubernetes liveness / readiness probes, etc.).
"""

from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from tempfile import TemporaryDirectory
from threading import Thread

import pytest

from competitive_intel_agents.web import WebDashboardHandler
from competitive_intel_agents.workspace import LocalWorkspace


@pytest.fixture
def server():
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


def _get(httpd, path):
    conn = HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    conn.request("GET", path)
    response = conn.getresponse()
    body = response.read()
    return response, body


def test_health_returns_200_when_process_alive(server):
    httpd, _ = server
    response, body = _get(httpd, "/health")
    assert response.status == 200
    assert "application/json" in response.getheader("Content-Type", "")
    payload = json.loads(body)
    assert payload == {"status": "ok"}


def test_ready_returns_200_when_workspace_readable(server):
    httpd, _ = server
    response, body = _get(httpd, "/ready")
    assert response.status == 200
    payload = json.loads(body)
    assert payload == {"status": "ready"}


def test_ready_returns_503_when_workspace_broken(server):
    httpd, workspace = server

    # Replace list_run_results with a callable that raises so we can
    # observe the readiness path's error branch without corrupting the
    # filesystem state.
    def _broken():
        raise RuntimeError("simulated storage outage")

    original = workspace.list_run_results
    workspace.list_run_results = _broken  # type: ignore[method-assign]
    try:
        response, body = _get(httpd, "/ready")
    finally:
        workspace.list_run_results = original  # type: ignore[method-assign]

    assert response.status == 503
    payload = json.loads(body)
    assert payload["status"] == "unready"
    assert "simulated storage outage" in payload["error"]


def test_health_does_not_require_auth_when_token_set(server, monkeypatch):
    """Health and ready must remain reachable for orchestrator probes
    even when the API token is configured. They live outside ``/api/``
    on purpose."""
    httpd, _ = server
    monkeypatch.setenv("CIA_API_TOKEN", "secret123")

    response, _ = _get(httpd, "/health")
    assert response.status == 200

    response, _ = _get(httpd, "/ready")
    assert response.status == 200
