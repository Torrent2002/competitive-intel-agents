"""Minimal web dashboard for local run inspection. Stdlib-only, no dependencies."""

from __future__ import annotations

import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, quote, unquote, urlparse

from competitive_intel_agents.dashboard import build_dashboard_snapshot
from competitive_intel_agents.models import CompetitiveIntelRequest, RunResult
from competitive_intel_agents.orchestrator import Orchestrator, load_agent_profiles
from competitive_intel_agents.provenance import build_provenance_graph
from competitive_intel_agents.runtime.model_runtime import ConfiguredProviderFactory, ModelRuntime
from competitive_intel_agents.runtime import (
    BingSearch,
    CachedWebFetch,
    DuckDuckGoSearch,
    FallbackSearch,
    ToolRuntime,
    WebFetchTool,
    WebSearchTool,
)
from competitive_intel_agents.harness import InMemoryCheckpointStore, RuntimeHarness

if TYPE_CHECKING:
    from competitive_intel_agents.workspace import LocalWorkspace


_STYLE = (
    "<style>\n"
    "*,*::before,*::after{box-sizing:border-box;}\n"
    "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
    "max-width:1120px;margin:0 auto;padding:1.5rem;line-height:1.6;"
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
    ".status.running,.status.empty{background:#dbeafe;color:#1e40af;}\n"
    ".meta{color:#6b7280;font-size:.85em;margin:.25rem 0;}\n"
    ".panel{background:#fff;border:1px solid #e5e7eb;border-radius:8px;"
    "padding:1rem;margin:1rem 0;}\n"
    ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));"
    "gap:.75rem;}\n"
    "label{display:block;font-weight:600;color:#374151;font-size:.9em;margin-bottom:.25rem;}\n"
    "input[type=text],textarea{width:100%;border:1px solid #d1d5db;border-radius:6px;"
    "padding:.65rem;font:inherit;background:#fff;}\n"
    "textarea{min-height:84px;resize:vertical;}\n"
    ".checks{display:flex;gap:1rem;flex-wrap:wrap;margin:.75rem 0;}\n"
    ".checks label{display:flex;align-items:center;gap:.4rem;font-weight:500;}\n"
    "button,.button{display:inline-block;border:0;border-radius:6px;background:#2563eb;"
    "color:#fff;padding:.65rem 1rem;font-weight:700;text-decoration:none;cursor:pointer;}\n"
    ".button.secondary{background:#475569;}\n"
    ".actions{display:flex;gap:.5rem;flex-wrap:wrap;margin:.75rem 0;}\n"
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
    ".workflow-section{margin:1.5rem 0 2rem;}\n"
    ".workflow{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));"
    "gap:.75rem;margin-top:.75rem;}\n"
    ".agent-card{position:relative;overflow:hidden;background:#fff;border:1px solid #dbe3ee;"
    "border-radius:8px;padding:1rem;min-height:150px;box-shadow:0 1px 2px rgba(15,23,42,.04);}\n"
    ".agent-card::before{content:\"\";position:absolute;inset:0 0 auto 0;height:3px;"
    "background:#cbd5e1;}\n"
    ".agent-card.is-running{border-color:transparent;background:linear-gradient(#fff,#fff) padding-box,"
    "linear-gradient(120deg,#22c55e,#06b6d4,#2563eb,#f59e0b,#22c55e) border-box;"
    "animation:agent-glow 2.4s linear infinite;box-shadow:0 0 0 1px rgba(37,99,235,.08),"
    "0 12px 30px rgba(37,99,235,.18);}\n"
    ".agent-card.is-running::before{height:100%;background:linear-gradient(110deg,"
    "transparent 0%,rgba(37,99,235,.08) 25%,rgba(34,197,94,.10) 50%,transparent 75%);"
    "animation:agent-sheen 1.8s ease-in-out infinite;}\n"
    ".agent-card.is-done::before{background:#22c55e;}\n"
    ".agent-card.is-rework::before{background:#f59e0b;}\n"
    ".agent-card.is-aborted::before{background:#ef4444;}\n"
    ".agent-card.is-blocked::before{background:#94a3b8;}\n"
    ".agent-name{position:relative;margin:0;color:#0f172a;font-size:1rem;}\n"
    ".agent-role{position:relative;color:#64748b;font-size:.85rem;margin:.15rem 0 .75rem;}\n"
    ".agent-status{position:relative;display:inline-block;padding:.12rem .5rem;border-radius:999px;"
    "font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0;}\n"
    ".agent-status.pending{background:#f1f5f9;color:#475569;}\n"
    ".agent-status.running{background:#dbeafe;color:#1d4ed8;}\n"
    ".agent-status.done{background:#dcfce7;color:#166534;}\n"
    ".agent-status.rework{background:#fef3c7;color:#92400e;}\n"
    ".agent-status.aborted{background:#fee2e2;color:#991b1b;}\n"
    ".agent-status.blocked{background:#e2e8f0;color:#334155;}\n"
    ".agent-meta{position:relative;color:#64748b;font-size:.8rem;margin:.6rem 0 0;}\n"
    ".thinking-dots{position:relative;display:flex;align-items:center;gap:.35rem;height:26px;margin-top:.8rem;}\n"
    ".thinking-dots span{width:7px;height:7px;border-radius:50%;background:#2563eb;"
    "animation:thinking-dot 1s ease-in-out infinite;}\n"
    ".thinking-dots span:nth-child(2){animation-delay:.14s;background:#06b6d4;}\n"
    ".thinking-dots span:nth-child(3){animation-delay:.28s;background:#22c55e;}\n"
    "@keyframes thinking-dot{0%,80%,100%{transform:translateY(0);opacity:.35;}40%{transform:translateY(-7px);opacity:1;}}\n"
    "@keyframes agent-sheen{0%{transform:translateX(-100%);}100%{transform:translateX(100%);}}\n"
    "@keyframes agent-glow{0%{filter:hue-rotate(0deg);}100%{filter:hue-rotate(360deg);}}\n"
    "@media (max-width:820px){.workflow{grid-template-columns:repeat(2,minmax(0,1fr));}}\n"
    "@media (max-width:520px){.workflow{grid-template-columns:1fr;}body{padding:1rem;}}\n"
    "section{margin-bottom:1.5rem;}\n"
    "</style>\n"
)


_WORKFLOW_AGENTS = (
    ("collector", "Collector", "Gathers market signals and sources"),
    ("analyst", "Analyst", "Turns sources into grounded claims"),
    ("writer", "Writer", "Shapes claims into the report draft"),
    ("reviewer", "Reviewer", "Checks evidence, clarity, and rework"),
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
        "<h1>Competitive Intel Operator Console</h1>\n"
        f"{_render_run_form()}"
        "<h2>Runs</h2>\n"
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
    display_status = result.status if result.status == "running" else snapshot.status
    sources = workspace.artifacts.list_sources(run_id)
    claims = workspace.artifacts.list_claims(run_id)
    report = workspace.artifacts.get_latest_report(run_id)
    events = workspace.journal.list_run_events(run_id)

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
    elif result.status in {"aborted", "rework_failed"}:
        report_html = "<p class=\"meta\">No report was produced because the run ended before writer.</p>\n"

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
    refresh_html = (
        '<meta http-equiv="refresh" content="2">'
        if result.status == "running"
        else ""
    )
    running_notice_html = (
        '<section class="panel"><p>Analysis is running. '
        "This page refreshes every 2 seconds.</p></section>"
        if result.status == "running"
        else ""
    )

    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        f"{refresh_html}\n"
        f"<title>Run {_esc(run_id)} — Competitive Intel</title>\n"
        f"{_STYLE}</head>\n<body>\n"
        f'<p class="back-link"><a href="/">&larr; Back to runs</a></p>\n'
        f"<h1>Run: {_esc(run_id)}</h1>\n"
        f'<p><span class="status {_esc(display_status)}">{_esc(display_status)}</span>'
        f" | Sources: {len(sources)}"
        f" | Claims: {len(claims)}"
        f" | Tool calls: {snapshot.tool_call_count}</p>\n"
        f"{running_notice_html}"
        f"{_render_export_actions(run_id) if report is not None else ''}"
        f"{_render_agent_workflow(events, result.status)}"
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


def _render_agent_workflow(events, run_status: str) -> str:
    states = _agent_workflow_states(events, run_status)
    cards = ""
    for agent, label, role in _WORKFLOW_AGENTS:
        state = states[agent]
        status = state["status"]
        thinking = (
            '<div class="thinking-dots" aria-label="thinking">'
            "<span></span><span></span><span></span></div>"
            if status == "running"
            else ""
        )
        cards += (
            f'<article class="agent-card {agent} is-{status}">'
            f'<h3 class="agent-name">{_esc(label)}</h3>'
            f'<p class="agent-role">{_esc(role)}</p>'
            f'<span class="agent-status {status}">{_esc(status)}</span>'
            f'<p class="agent-meta">Rounds: {state["rounds"]}'
            f' | Last: {_esc(state["decision"])}</p>'
            f"{thinking}</article>\n"
        )
    return (
        '<section class="workflow-section"><h2>Agent Workflow</h2>\n'
        '<div class="workflow">\n'
        f"{cards}</div></section>\n"
    )


def _agent_workflow_states(events, run_status: str) -> dict[str, dict[str, object]]:
    agent_order = [agent for agent, _, _ in _WORKFLOW_AGENTS]
    states: dict[str, dict[str, object]] = {
        agent: {"status": "pending", "rounds": 0, "decision": "-"}
        for agent in agent_order
    }
    events_by_agent = {agent: [] for agent in agent_order}
    for event in events:
        events_by_agent[event.agent].append(event)

    for agent in agent_order:
        agent_events = events_by_agent[agent]
        if not agent_events:
            continue
        latest = agent_events[-1]
        status = "done"
        if latest.decision == "abort":
            status = "aborted"
        elif latest.decision == "rework":
            status = "rework"
        states[agent] = {
            "status": status,
            "rounds": len(agent_events),
            "decision": latest.decision,
        }

    if run_status == "running":
        running_agent = _infer_running_agent(events, states, agent_order)
        if running_agent is not None:
            states[running_agent]["status"] = "running"
            if states[running_agent]["decision"] == "-":
                states[running_agent]["decision"] = "active"
    elif run_status in {"aborted", "rework_failed"}:
        _mark_terminal_agent(states, "aborted")
        _mark_pending_agents(states, "blocked")
    elif run_status in {"needs_rework"}:
        _mark_rework_targets(events, states)

    return states


def _infer_running_agent(events, states, agent_order):
    if not events:
        return agent_order[0]
    latest = events[-1]
    if latest.decision in {"continue", "retry"}:
        return latest.agent
    if latest.decision == "rework":
        feedback_targets = [
            item.target_agent
            for item in latest.review_feedback
            if item.target_agent in states
        ]
        return feedback_targets[0] if feedback_targets else latest.agent
    if latest.decision == "stop":
        index = agent_order.index(latest.agent)
        if index + 1 < len(agent_order):
            return agent_order[index + 1]
    return None


def _mark_terminal_agent(states, status: str) -> None:
    for state in reversed(list(states.values())):
        if state["status"] != "pending":
            state["status"] = status
            return


def _mark_pending_agents(states, status: str) -> None:
    for state in states.values():
        if state["status"] == "pending":
            state["status"] = status


def _mark_rework_targets(events, states) -> None:
    for event in reversed(events):
        if event.review_feedback:
            for item in event.review_feedback:
                if item.target_agent in states:
                    states[item.target_agent]["status"] = "rework"
            return


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_run_form() -> str:
    return (
        '<section class="panel">\n'
        "<h2>Run Analysis</h2>\n"
        '<form method="post" action="/runs">\n'
        '<div class="grid">\n'
        '<div><label>Company / Product</label>'
        '<input name="company" type="text" placeholder="Notion" required></div>\n'
        '<div><label>Market</label>'
        '<input name="market" type="text" placeholder="productivity software"></div>\n'
        '<div><label>Competitors</label>'
        '<input name="competitors" type="text" placeholder="Coda, Airtable"></div>\n'
        '</div>\n'
        '<div style="margin-top:.75rem"><label>Questions</label>'
        '<textarea name="questions" placeholder="pricing, collaboration, positioning"></textarea></div>\n'
        '<div class="checks">\n'
        '<label><input type="checkbox" name="real_web" value="1"> Real web collection</label>\n'
        '<label><input type="checkbox" name="real_model" value="1"> Real model</label>\n'
        '</div>\n'
        '<button type="submit">Run Analysis</button>\n'
        '</form>\n'
        '</section>\n'
    )


def _render_export_actions(run_id: str) -> str:
    encoded = quote(run_id)
    return (
        '<div class="actions">'
        f'<a class="button secondary" href="/runs/{encoded}/export?format=markdown">Markdown</a>'
        f'<a class="button secondary" href="/runs/{encoded}/export?format=json">JSON</a>'
        f'<a class="button secondary" href="/runs/{encoded}/export?format=html">HTML</a>'
        "</div>"
    )


def create_run_from_form(
    workspace: "LocalWorkspace",
    form: dict[str, list[str]],
) -> RunResult:
    request = _request_from_form(form)
    real_web = _truthy(form, "real_web")
    real_model = _truthy(form, "real_model")
    orchestrator = _make_web_orchestrator(workspace, real_web=real_web, real_model=real_model)
    result = orchestrator.run(request)
    workspace.save_run_result(result)
    return result


def start_run_from_form(
    workspace: "LocalWorkspace",
    form: dict[str, list[str]],
) -> RunResult:
    """Create a pending run and execute the heavy pipeline in a background thread."""

    request = _request_from_form(form)
    real_web = _truthy(form, "real_web")
    real_model = _truthy(form, "real_model")
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    pending = RunResult(run_id=run_id, status="running")
    workspace.save_run_result(pending)

    def _run_background() -> None:
        try:
            orchestrator = _make_web_orchestrator(
                workspace,
                real_web=real_web,
                real_model=real_model,
                run_id=run_id,
            )
            result = orchestrator.run(request)
        except Exception as exc:
            result = RunResult(run_id=run_id, status="aborted", error=str(exc))
        workspace.save_run_result(result)

    Thread(target=_run_background, daemon=True).start()
    return pending


def _request_from_form(form: dict[str, list[str]]) -> CompetitiveIntelRequest:
    return CompetitiveIntelRequest(
        company=_first(form, "company"),
        market=_first(form, "market") or None,
        competitors=_split_csv(_first(form, "competitors")),
        questions=_split_csv(_first(form, "questions")),
    )


def _make_web_orchestrator(
    workspace: "LocalWorkspace",
    real_web: bool,
    real_model: bool,
    run_id: str | None = None,
) -> Orchestrator:
    model_runtime = None
    if real_model:
        model_runtime = ModelRuntime(provider=ConfiguredProviderFactory().create())
    if not real_web:
        return Orchestrator(
            artifacts=workspace.artifacts,
            journal=workspace.journal,
            agent_profiles=load_agent_profiles(),
            model_runtime=model_runtime,
            enable_rework=True,
            run_id_factory=(lambda: run_id) if run_id else None,
        )

    tools = ToolRuntime()
    tools.register(WebSearchTool(FallbackSearch([BingSearch(), DuckDuckGoSearch(timeout=2)])))
    tools.register(
        CachedWebFetch(
            WebFetchTool(),
            cache_dir=workspace.path / "cache" / "web_fetch",
        )
    )
    return Orchestrator(
        artifacts=workspace.artifacts,
        journal=workspace.journal,
        agent_profiles=load_agent_profiles(),
        harness=RuntimeHarness(workspace.journal, tools, InMemoryCheckpointStore()),
        model_runtime=model_runtime,
        enable_rework=True,
        run_id_factory=(lambda: run_id) if run_id else None,
    )


def _first(form: dict[str, list[str]], key: str) -> str:
    values = form.get(key, [])
    return values[0].strip() if values else ""


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _truthy(form: dict[str, list[str]], key: str) -> bool:
    return _first(form, key) in {"1", "true", "on", "yes"}


class WebDashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves run list and run detail from workspace."""

    workspace: "LocalWorkspace"

    def log_message(self, fmt, *args):
        pass  # suppress stderr logging during tests

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            html = render_run_list(self.workspace)
            self._respond_html(200, html)
        elif parsed.path.startswith("/runs/") and parsed.path.endswith("/export"):
            run_id = unquote(parsed.path[len("/runs/"):-len("/export")].strip("/"))
            query = parse_qs(parsed.query)
            fmt = _first(query, "format") or "markdown"
            self._respond_export(run_id, fmt)
        elif parsed.path.startswith("/runs/"):
            run_id = unquote(parsed.path[len("/runs/"):])
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

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/runs":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        form = parse_qs(body)
        try:
            if _truthy(form, "real_web") or _truthy(form, "real_model"):
                result = start_run_from_form(self.workspace, form)
            else:
                result = create_run_from_form(self.workspace, form)
        except Exception as exc:
            self._respond_html(400, _render_error(str(exc)))
            return
        self.send_response(303)
        self.send_header("Location", f"/runs/{quote(result.run_id)}")
        self.end_headers()

    def _respond_html(self, code: int, html: str):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond_export(self, run_id: str, fmt: str):
        from competitive_intel_agents.export import export_run

        try:
            content = export_run(self.workspace.artifacts, self.workspace.journal, run_id, fmt)
        except Exception as exc:
            self._respond_html(400, _render_error(str(exc)))
            return
        content_type = {
            "html": "text/html; charset=utf-8",
            "json": "application/json; charset=utf-8",
            "markdown": "text/markdown; charset=utf-8",
        }.get(fmt, "text/plain; charset=utf-8")
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _render_error(message: str) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"{_STYLE}<title>Error</title></head><body>"
        '<p class="back-link"><a href="/">&larr; Back</a></p>'
        "<h1>Run failed</h1>"
        f'<section class="panel"><p>{_esc(message)}</p></section>'
        "</body></html>"
    )


def start_web_server(
    workspace: "LocalWorkspace",
    host: str = "127.0.0.1",
    port: int = 8080,
) -> None:
    """Start the web dashboard server (blocking)."""
    WebDashboardHandler.workspace = workspace
    server = ThreadingHTTPServer((host, port), WebDashboardHandler)
    try:
        print(f"Web dashboard: http://{host}:{port}")
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


__all__ = [
    "WebDashboardHandler",
    "create_run_from_form",
    "start_run_from_form",
    "render_run_list",
    "render_run_detail",
    "start_web_server",
]
