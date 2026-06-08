# 27 Basic Web Dashboard

## Goal

Provide a minimal browser-based run dashboard for demos and inspection.

## Scope

In scope:

- Local-only web server.
- List runs from workspace.
- Show dashboard summary.
- Show sources, claims, report, reviewer feedback, and journal events.
- No auth by default; bind to localhost.

Out of scope:

- Multi-user production deployment.
- Real-time streaming.
- Editing artifacts.

## Suggested Stack

- FastAPI or standard-library HTTP server for API/static files.
- Simple HTML/CSS/JS or server-rendered pages.
- Read from persistent workspace stores.

## Tests

- Server can render run list.
- Run detail page includes status, agents, artifacts, and report.
- Missing run returns a readable 404.

## Done Criteria

- A user can open a browser and inspect a completed run.
- Web UI reads stores and does not call agents directly.
