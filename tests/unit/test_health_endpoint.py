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


def test_sigterm_handler_does_not_deadlock(tmp_path):
    """Regression test for PR #24 review M2.

    ``server.shutdown()`` blocks until ``serve_forever()`` returns. The
    earlier implementation called ``shutdown`` from inside the signal
    handler, which runs on the main thread — the same thread parked in
    ``serve_forever``. That deadlocks until the kernel SIGKILLs the
    container ``terminationGracePeriodSeconds`` later, defeating the
    whole \"graceful shutdown\" goal.

    This test forks a child process running ``start_web_server``, waits
    for the listener to come up, sends SIGTERM, and asserts the child
    exits cleanly within a few seconds. If the deadlock returns the test
    times out and ``proc.terminate``/``kill`` paths force a hard fail.
    """
    import signal as _signal
    import socket
    import subprocess
    import sys
    import textwrap
    import time

    workspace_path = tmp_path / "ws"

    # Pick a free port up front so the child does not need to negotiate.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    child_script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {repr(str(tmp_path.parent.parent / 'src'))})
        from competitive_intel_agents.web import start_web_server
        from competitive_intel_agents.workspace import LocalWorkspace
        ws = LocalWorkspace({repr(str(workspace_path))})
        start_web_server(ws, host="127.0.0.1", port={port})
        """
    )

    proc = subprocess.Popen(
        [sys.executable, "-c", child_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for the listener — up to 10s so a slow CI runner doesn't
        # flake. We poll the actual TCP port, not /health, because
        # /health requires the server to be fully serving.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            with socket.socket() as probe:
                probe.settimeout(0.2)
                try:
                    probe.connect(("127.0.0.1", port))
                except OSError:
                    time.sleep(0.05)
                    continue
                else:
                    break
        else:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=2)
            raise AssertionError(
                f"server did not start within 10s\nstdout={stdout!r}\nstderr={stderr!r}"
            )

        # Give the signal handlers a moment to register before sending.
        time.sleep(0.1)
        proc.send_signal(_signal.SIGTERM)

        # The fix should let the process exit within ~1s; we allow 8s
        # for slow CI. Anything longer than that and the deadlock is
        # back.
        try:
            return_code = proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=2)
            raise AssertionError(
                "SIGTERM did not terminate the server within 8s — "
                "shutdown() likely deadlocked on the main thread.\n"
                f"stdout={stdout!r}\nstderr={stderr!r}"
            )

        # SIGTERM-induced clean shutdown returns 0 from this code path.
        assert return_code == 0, f"non-zero exit: {return_code}"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
