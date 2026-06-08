"""Bounded reviewer-feedback rework loop."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from competitive_intel_agents.agents import (
    Agent,
    AnalystAgent,
    CollectorAgent,
    ReviewerAgent,
    WriterAgent,
)
from competitive_intel_agents.artifacts import ArtifactNotFoundError, ArtifactStore
from competitive_intel_agents.models import (
    AgentName,
    AnalysisClaim,
    ReportDraft,
    ReviewFeedback,
    RunContext,
    SourceArtifact,
)


REWORK_ROUTES: dict[AgentName, list[AgentName]] = {
    "collector": ["collector", "analyst", "writer", "reviewer"],
    "analyst": ["analyst", "writer", "reviewer"],
    "writer": ["writer", "reviewer"],
    "reviewer": ["reviewer"],
}


class Harness(Protocol):
    def run_agent(self, context: RunContext, agent: Agent):
        ...


@dataclass(frozen=True)
class ReworkResult:
    status: str
    attempts: int
    route: list[AgentName]
    replacement_artifact_ids: list[str]
    final_decision: str | None = None


def route_feedback(feedback: ReviewFeedback) -> list[AgentName]:
    return list(REWORK_ROUTES[feedback.target_agent])


class ReworkLoop:
    """Apply reviewer feedback with bounded attempts and artifact lineage."""

    def __init__(
        self,
        artifacts: ArtifactStore,
        harness: Harness,
        max_attempts: int = 2,
    ) -> None:
        self._artifacts = artifacts
        self._harness = harness
        self._max_attempts = max_attempts
        self._attempts: dict[tuple[str, str, str], int] = {}

    def apply(self, context: RunContext, feedback: ReviewFeedback) -> ReworkResult:
        key = (feedback.issue, feedback.target_agent, feedback.target_artifact_id)
        attempts = self._attempts.get(key, 0)
        if attempts >= self._max_attempts:
            return ReworkResult(
                status="max_attempts_exceeded",
                attempts=attempts,
                route=[],
                replacement_artifact_ids=[],
            )
        attempts += 1
        self._attempts[key] = attempts

        route = route_feedback(feedback)
        replacements = self._prepare_artifact_changes(context, feedback)
        final_decision = self._run_route(context, route)
        return ReworkResult(
            status="applied",
            attempts=attempts,
            route=route,
            replacement_artifact_ids=replacements,
            final_decision=final_decision,
        )

    def _prepare_artifact_changes(
        self, context: RunContext, feedback: ReviewFeedback
    ) -> list[str]:
        replacements: list[str] = []
        try:
            artifact = self._artifacts.get_artifact(feedback.target_artifact_id)
        except ArtifactNotFoundError:
            if feedback.target_agent == "collector":
                replacement = SourceArtifact(
                    id=self._replacement_id(feedback.target_artifact_id, 1),
                    run_id=context.run_id,
                    url=f"https://rework.local/{feedback.target_artifact_id}",
                    title=f"Rework source for {feedback.target_artifact_id}",
                    snippet=feedback.required_action,
                )
                self._artifacts.save_source(replacement)
                replacements.append(replacement.id)
            self._reject_downstream(context.run_id, feedback.target_agent)
            return replacements

        replacement = self._replacement_from_artifact(artifact, feedback)
        if isinstance(replacement, SourceArtifact):
            self._artifacts.save_source(replacement)
        elif isinstance(replacement, AnalysisClaim):
            self._artifacts.save_claim(replacement)
        else:
            self._artifacts.save_report(replacement)
        self._artifacts.mark_superseded(artifact.id, replacement.id)
        replacements.append(replacement.id)
        self._reject_downstream(context.run_id, feedback.target_agent)
        return replacements

    def _replacement_from_artifact(
        self,
        artifact: SourceArtifact | AnalysisClaim | ReportDraft,
        feedback: ReviewFeedback,
    ) -> SourceArtifact | AnalysisClaim | ReportDraft:
        replacement_id = self._replacement_id(artifact.id, artifact.version + 1)
        common = {
            "id": replacement_id,
            "version": artifact.version + 1,
            "supersedes_id": artifact.id,
            "status": "active",
        }
        if isinstance(artifact, SourceArtifact):
            return replace(
                artifact,
                **common,
                snippet=f"{artifact.snippet}\nRework: {feedback.required_action}".strip(),
            )
        if isinstance(artifact, AnalysisClaim):
            return replace(
                artifact,
                **common,
                reasoning=f"{artifact.reasoning}\nRework: {feedback.required_action}".strip(),
            )
        sections = dict(artifact.sections)
        if feedback.issue == "missing_section":
            section = _section_from_feedback(feedback)
            sections.setdefault(section, feedback.required_action)
        else:
            sections["Rework notes"] = feedback.required_action
        return replace(artifact, **common, sections=sections)

    def _reject_downstream(self, run_id: str, target_agent: AgentName) -> None:
        if target_agent in {"collector", "analyst"}:
            for report in self._artifacts.list_reports(run_id):
                self._artifacts.mark_rejected(report.id, "Stale after upstream rework")
        if target_agent == "collector":
            for claim in self._artifacts.list_claims(run_id):
                self._artifacts.mark_rejected(claim.id, "Stale after source rework")

    def _run_route(self, context: RunContext, route: list[AgentName]) -> str | None:
        final_decision: str | None = None
        agents = self._build_agents()
        for agent_name in route:
            result = self._harness.run_agent(context, agents[agent_name])
            final_decision = result.decision
        return final_decision

    def _build_agents(self) -> dict[AgentName, Agent]:
        return {
            "collector": CollectorAgent(self._artifacts),
            "analyst": AnalystAgent(self._artifacts),
            "writer": WriterAgent(self._artifacts),
            "reviewer": ReviewerAgent(self._artifacts),
        }

    @staticmethod
    def _replacement_id(artifact_id: str, version: int) -> str:
        return f"{artifact_id}_v{version}"


def _section_from_feedback(feedback: ReviewFeedback) -> str:
    for section in WriterAgent.REQUIRED_SECTIONS:
        if section.lower() in feedback.message.lower():
            return section
    return "Rework notes"
