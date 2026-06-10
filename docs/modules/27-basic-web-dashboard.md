# 27 Basic Web Dashboard

## Goal

Expose persisted runs through a minimal browser dashboard. Run detail should
make the four-agent workflow visible before the artifact tables.

## Scope

In scope:

- Local-only web server.
- List runs from workspace.
- Render workflow map at `/workflow`.
- Show Agent Workflow before report/tables.
- Show status, report, sources, claims, reviewer feedback, journal events, and
  provenance summary.
- Auto-refresh running runs.
- Show thinking/border animation for the active running agent.
- Surface source metadata such as `content_ref`, `char_count`, and coverage hints.
- No auth by default; bind to localhost.

Out of scope:

- Multi-user production deployment.
- Editing artifacts.
- JS-heavy client-side state.

## Routes

- `/` shows run list.
- `/runs/<run_id>` shows run detail.
- `/workflow` shows the workflow map and collaboration contract summary.

## Detail Sections

1. Run summary.
2. Workflow map link.
3. Agent Workflow.
4. Report.
5. Sources table.
6. Claims table.
7. Reviewer feedback.
8. Journal events.
9. Provenance summary.

## Agent Workflow State

The frontend derives state from persisted run data. It does not invent a second
state machine.

| State | Meaning |
|---|---|
| `pending` | Agent has not started. |
| `running` | Current active agent while run status is running. |
| `done` | Agent stopped successfully. |
| `rework` | Reviewer or rework loop points to this agent. |
| `blocked` | Upstream stage prevented execution. |
| `aborted` | Agent or run aborted. |

## Tests

- Server can render run list.
- Run detail page includes status, agents, artifacts, and report.
- Workflow map route renders.
- Missing run returns a readable 404.
- Running runs auto-refresh and show active agent animation.
- Source metadata exposes persisted content references when present.

## Done Criteria

- A user can open a browser and inspect a completed or running run.
- Web UI reads stores and does not call agents directly.
- Agent collaboration is visible before raw tables.
- Frontend state follows `RunResult`, `RoundEvent`, and `ReviewFeedback`.
