"""Minimal web dashboard for local run inspection. Stdlib-only, no dependencies."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from typing import TYPE_CHECKING

from competitive_intel_agents.dashboard import build_dashboard_snapshot
from competitive_intel_agents.provenance import build_provenance_graph

if TYPE_CHECKING:
    from competitive_intel_agents.workspace import LocalWorkspace


_STYLE = (
    "<style>\n"
    "*,*::before,*::after{box-sizing:border-box;}\n"
    "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
    "max-width:960px;margin:0 auto;padding:1.5rem;line-height:1.6;"
    "color:#1a1a1a;background:#fafafa;}\n"
    "h1{color:#1e3a5f;border-bottom:2px solid #2563eb;padding-bottom:.5rem;}\n"
    "h2{color:#2563eb;margin-top:2rem;}\n"
    "h3{color:#374151;margin-top:1.5rem;}\n"
    ".run-card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;"
    "padding:1rem;margin-bottom:.75rem;"
    "transition:box-shadow .15s;}\n"
    ".run-card:hover{box-shadow:0 2px 8px rgba(0,0,0,.08);}\n"
    ".run-card a{text-decoration:none;color:#2563eb;font-weight:600;}\n"
    ".status{display:inline-block;padding:.15em .6em;border-radius:12px;"
    "font-size:.8em;font-weight:600;}\n"
    ".status.completed{background:#d1fae5;color:#065f46;}\n"
    ".status.needs_rework{background:#fef3c7;color:#92400e;}\n"
    ".status.aborted{background:#fee2e2;color:#991b1b;}\n"
    ".meta{color:#6b7280;font-size:.85em;margin:.25rem 0;}\n"
    "table{border-collapse:collapse;width:100%;}\n"
    "th,td{text-align:left;padding:.5rem;border-bottom:1px solid #e5e7eb;}\n"
    "th{color:#374151;font-size:.85em;text-transform:uppercase;}\n"
    "code{background:#f3f4f6;padding:.1em .3em;border-radius:3px;font-size:.9em;}\n"
    ".back-link{font-size:.9em;margin-bottom:1rem;}\n"
    ".back-link a{color:#2563eb;}\n"
    ".badge{display:inline-block;padding:.1em .5em;border-radius:8px;"
    "font-size:.75em;font-weight:600;margin-right:.25em;}\n"
    ".badge-high{background:#d1fae5;color:#065f46;}\n"
    ".badge-medium{background:#fef3c7;color:#92400e;}\n"
    ".badge-low{background:#fee2e2;color:#991b1b;}\n"
    "section{margin-bottom:1.5rem;}\n"
    "</style>\n"
)


def render_run_list(workspace: "LocalWorkspace") -> str:
    """Render the run list page HTML."""
    results = workspace.list_run_results()
    rows = ""
    for r in results:
        rows += (
            f'<div class="run-card">'
            f'<a href="/runs/{_esc(r.run_id)}">{_esc(r.run_id)}</a>'
            f' <span class="status {_esc(r.status)}">{_esc(r.status)}</span>'
            f'<p class="meta">Report: <code>{_esc(r.report_id or "-")}</code>'
        )
        if r.review_feedback:
            rows += f" | Feedback: {len(r.review_feedback)} item(s)"
        rows += "</p></div>\n"

    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<title>Competitive Intel — Runs</title>\n"
        f"{_STYLE}</head>\n<body>\n"
        "<h1>Competitive Intel — Runs</h1>\n"
        f"<p>{len(results)} run(s)</p>\n"
        f"{rows}"
        "\n</body>\n</html>\n"
    )


def render_run_detail(workspace: "LocalWorkspace", run_id: str) -> str | None:
    """Render the run detail page HTML, or None if run is not found."""
    result = workspace.get_run_result(run_id)
    if result is None:
        return None

    snapshot = build_dashboard_snapshot(
        workspace.journal, workspace.artifacts, run_id
    )
    sources = workspace.artifacts.list_sources(run_id)
    claims = workspace.artifacts.list_claims(run_id)
    report = workspace.artifacts.get_latest_report(run_id)

    # Sources table
    sources_rows = ""
    for s in sources:
        sources_rows += (
            f"<tr><td><code>{_esc(s.id)}</code></td>"
            f"<td><a href=\"{_esc(s.url)}\">{_esc(s.title)}</a></td>"
            f"<td>{_esc(s.snippet[:200])}</td></tr>\n"
        )

    # Claims table
    claims_rows = ""
    for c in claims:
        conf_cls = c.confidence if c.confidence in ("high", "medium", "low") else "medium"
        claims_rows += (
            f"<tr><td><code>{_esc(c.id)}</code></td>"
            f"<td>{_esc(c.text)}</td>"
            f"<td><span class=\"badge badge-{conf_cls}\">{_esc(c.confidence)}</span></td>"
            f"<td>{', '.join(_esc(sid) for sid in c.source_ids)}</td></tr>\n"
        )

    # Report sections
    report_html = ""
    if report is not None:
        for section, content in report.sections.items():
            report_html += (
                f"<h3>{_esc(section)}</h3>\n"
                f"<div>{_esc(content)}</div>\n"
            )

    # Reviewer feedback
    feedback_html = ""
    if result.review_feedback:
        items = ""
        for item in result.review_feedback:
            items += (
                f"<li><strong>{_esc(item.issue)}</strong> → "
                f"{_esc(item.target_agent)} "
                f"(<code>{_esc(item.target_artifact_id)}</code>): "
                f"{_esc(item.message)}</li>\n"
            )
        feedback_html = (
            f"<section><h2>Reviewer Feedback ({len(result.review_feedback)})</h2>"
            f"<ul>{items}</ul></section>"
        )

    # Journal events
    events = workspace.journal.list_run_events(run_id)
    events_rows = ""
    for e in events:
        signals_str = ", ".join(e.signals) if e.signals else "-"
        events_rows += (
            f"<tr><td><code>{_esc(e.id)}</code></td>"
            f"<td>{_esc(e.agent)}</td>"
            f"<td>{e.round}</td>"
            f"<td>{_esc(e.decision)}</td>"
            f"<td>{signals_str}</td>"
            f"<td>{len(e.tool_calls)} calls, {len(e.output_artifact_ids)} artifacts</td></tr>\n"
        )

    # Provenance summary
    provenance = build_provenance_graph(
        workspace.journal, workspace.artifacts, run_id,
        report.id if report else None,
    )
    provenance_summary = (
        f"<p>Nodes: {len(provenance.nodes)}, Edges: {len(provenance.edges)}</p>"
    )

    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        f"<title>Run {_esc(run_id)} — Competitive Intel</title>\n"
        f"{_STYLE}</head>\n<body>\n"
        f'<p class="back-link"><a href="/">&larr; Back to runs</a></p>\n'
        f"<h1>Run: {_esc(run_id)}</h1>\n"
        f'<p><span class="status {_esc(snapshot.status)}">{_esc(snapshot.status)}</span>'
        f" | Sources: {len(sources)}"
        f" | Claims: {len(claims)}"
        f" | Tool calls: {snapshot.tool_call_count}</p>\n"
        f"<section><h2>Report</h2>\n{report_html}</section>\n"
        f"<section><h2>Sources ({len(sources)})</h2>\n"
        f"<table><tr><th>ID</th><th>Title</th><th>Snippet</th></tr>"
        f"{sources_rows}</table></section>\n"
        f"<section><h2>Claims ({len(claims)})</h2>\n"
        f"<table><tr><th>ID</th><th>Text</th><th>Confidence</th><th>Source IDs</th></tr>"
        f"{claims_rows}</table></section>\n"
        f"{feedback_html}"
        f"<section><h2>Journal Events ({len(events)})</h2>\n"
        f"<table><tr><th>ID</th><th>Agent</th><th>Round</th><th>Decision</th>"
        f"<th>Signals</th><th>Details</th></tr>"
        f"{events_rows}</table></section>\n"
        f"<section><h2>Provenance</h2>\n{provenance_summary}</section>\n"
        "<section><h2>Agent Rounds</h2>\n<ul>\n" +
        "".join(
            f"<li>{agent}: {rds} rounds</li>"
            for agent, rds in snapshot.agent_rounds.items()
        ) +
        "</ul></section>\n"
        "<section><h2>Health Signals</h2>\n<ul>\n" +
        "".join(f"<li>{_esc(s)}</li>" for s in snapshot.health_signals) +
        "</ul></section>\n"
        "\n</body>\n</html>\n"
    )


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class WebDashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves run list and run detail from workspace."""

    workspace: "LocalWorkspace"

    def log_message(self, fmt, *args):
        pass  # suppress stderr logging during tests

    def do_GET(self):
        if self.path == "/":
            html = render_run_list(self.workspace)
            self._respond_html(200, html)
        elif self.path.startswith("/runs/"):
            run_id = self.path[len("/runs/"):]
            html = render_run_detail(self.workspace, run_id)
            if html is None:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(
                    f"<h1>404 — run not found: {_esc(run_id)}</h1>".encode()
                )
            else:
                self._respond_html(200, html)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def _respond_html(self, code: int, html: str):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_web_server(
    workspace: "LocalWorkspace",
    host: str = "127.0.0.1",
    port: int = 8080,
) -> None:
    """Start the web dashboard server (blocking)."""
    WebDashboardHandler.workspace = workspace
    server = HTTPServer((host, port), WebDashboardHandler)
    try:
        print(f"Web dashboard: http://{host}:{port}")
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


__all__ = [
    "WebDashboardHandler",
    "render_run_list",
    "render_run_detail",
    "start_web_server",
]
