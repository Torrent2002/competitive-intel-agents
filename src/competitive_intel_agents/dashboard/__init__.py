"""Terminal observability dashboard for a single run."""

from __future__ import annotations

from dataclasses import dataclass, field

from competitive_intel_agents.artifacts import ArtifactStore
from competitive_intel_agents.journal import JournalStore
from competitive_intel_agents.models import AgentName, RoundEvent


@dataclass(frozen=True)
class DashboardSnapshot:
    run_id: str
    status: str
    agent_rounds: dict[AgentName, int] = field(default_factory=dict)
    tool_call_count: int = 0
    source_count: int = 0
    claim_count: int = 0
    report_id: str | None = None
    review_feedback_count: int = 0
    health_signals: list[str] = field(default_factory=list)


def build_dashboard_snapshot(
    journal: JournalStore,
    artifacts: ArtifactStore,
    run_id: str,
) -> DashboardSnapshot:
    """Build a structured terminal-dashboard summary from stores only."""

    events = journal.list_run_events(run_id)
    if not events:
        return DashboardSnapshot(run_id=run_id, status="empty")

    report = artifacts.get_latest_report(run_id)
    return DashboardSnapshot(
        run_id=run_id,
        status=_run_status(events),
        agent_rounds=_agent_rounds(events),
        tool_call_count=sum(len(event.tool_calls) for event in events),
        source_count=len(artifacts.list_sources(run_id)),
        claim_count=len(artifacts.list_claims(run_id)),
        report_id=report.id if report is not None else None,
        review_feedback_count=sum(len(event.review_feedback) for event in events),
        health_signals=_health_signals(events),
    )


def render_dashboard(snapshot: DashboardSnapshot) -> str:
    """Render a compact human-readable terminal dashboard."""

    lines = [
        f"Run: {snapshot.run_id}",
        f"Status: {snapshot.status}",
        f"Sources: {snapshot.source_count}",
        f"Claims: {snapshot.claim_count}",
        f"Tool calls: {snapshot.tool_call_count}",
        f"Reviewer feedback: {snapshot.review_feedback_count}",
    ]
    if snapshot.report_id:
        lines.append(f"Report: {snapshot.report_id}")
    if snapshot.agent_rounds:
        lines.append("Agent rounds:")
        for agent, rounds in snapshot.agent_rounds.items():
            lines.append(f"- {agent}: {rounds}")
    if snapshot.health_signals:
        lines.append("Signals:")
        for signal in snapshot.health_signals:
            lines.append(f"- {signal}")
    return "\n".join(lines)


def _run_status(events: list[RoundEvent]) -> str:
    if any(event.decision == "abort" for event in events):
        return "aborted"
    if any(event.decision == "rework" for event in events):
        return "needs_rework"
    if events[-1].decision == "stop":
        return "completed"
    return events[-1].decision


def _agent_rounds(events: list[RoundEvent]) -> dict[AgentName, int]:
    rounds: dict[AgentName, int] = {}
    for event in events:
        rounds[event.agent] = rounds.get(event.agent, 0) + 1
    return rounds


def _health_signals(events: list[RoundEvent]) -> list[str]:
    signals: list[str] = []
    for event in events:
        for signal in event.signals:
            if signal not in signals:
                signals.append(signal)
    return signals


__all__ = [
    "DashboardSnapshot",
    "build_dashboard_snapshot",
    "render_dashboard",
]
