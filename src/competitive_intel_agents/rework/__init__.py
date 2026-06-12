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
from competitive_intel_agents.journal import JournalStore
from competitive_intel_agents.memory import ConversationStore
from competitive_intel_agents.models import (
    AgentName,
    AnalysisClaim,
    ReportDraft,
    ReviewFeedback,
    RunContext,
    SourceArtifact,
)
from competitive_intel_agents.runtime.model_runtime import ModelRuntime


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
        journal: JournalStore | None = None,
        model_runtime: ModelRuntime | None = None,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._harness = harness
        self._max_attempts = max_attempts
        self._journal = journal
        self._model_runtime = model_runtime
        self._conversation_store = conversation_store
        self._attempts: dict[tuple[str, str, str], int] = {}

    def apply(
        self,
        context: RunContext,
        feedback: ReviewFeedback,
        all_feedback: list[ReviewFeedback] | None = None,
    ) -> ReworkResult:
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
        route_context = self._context_with_feedback(context, all_feedback or [feedback])
        final_decision = self._run_route(route_context, route)
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
                    id=self._next_available_replacement_id(
                        feedback.target_artifact_id,
                    ),
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
        for agent_name in route:
            self._harness.reset_retry_counts(agent_name)
            result = self._harness.run_agent(context, self._build_agent(context, agent_name))
            final_decision = result.decision
        return final_decision

    def _build_agent(self, context: RunContext, agent_name: AgentName) -> Agent:
        if agent_name == "collector":
            existing_sources = self._artifacts.list_sources(context.run_id)
            target_sources = max(2, len(existing_sources) + 2)
            return CollectorAgent(
                self._artifacts,
                target_sources=target_sources,
                model_runtime=self._model_runtime,
            )
        if agent_name == "analyst":
            return AnalystAgent(
                self._artifacts,
                model_runtime=self._model_runtime,
                conversation_store=self._conversation_store,
            )
        if agent_name == "writer":
            return WriterAgent(
                self._artifacts,
                model_runtime=self._model_runtime,
                conversation_store=self._conversation_store,
            )
        return ReviewerAgent(
            self._artifacts,
            journal=self._journal,
            model_runtime=self._model_runtime,
            conversation_store=self._conversation_store,
        )

    def _context_with_feedback(
        self,
        context: RunContext,
        feedback_items: list[ReviewFeedback],
    ) -> RunContext:
        metadata = dict(context.metadata)
        # Group feedback by target agent so each agent reads only its own
        by_agent: dict[str, list[dict]] = {}
        for fb in feedback_items:
            by_agent.setdefault(fb.target_agent, []).append({
                "issue": fb.issue,
                "message": fb.message,
                "required_action": fb.required_action,
                "severity": fb.severity,
                "entity": fb.entity,
                "dimension": fb.dimension,
                "question": fb.question,
            })
        metadata["rework_feedback"] = by_agent
        # Collector rework plan (for missing_source targeting collector)
        for fb in feedback_items:
            if fb.target_agent == "collector" and fb.issue == "missing_source":
                metadata["collector_rework_plan"] = self._collector_rework_plan(context, fb)
                break
        return replace(context, metadata=metadata)

    @staticmethod
    def _collector_rework_plan(
        context: RunContext,
        feedback: ReviewFeedback,
    ) -> dict:
        entity = feedback.entity or context.request.company
        entity_role = "self" if entity == context.request.company else "competitor"
        dimension = feedback.dimension or _dimension_from_feedback(feedback)
        source_type = (
            "data_provider"
            if dimension in {"market_share", "audience"}
            else "industry_report"
        )
        queries = _targeted_queries(context, entity, dimension, feedback)
        return {
            "entity": entity,
            "entity_role": entity_role,
            "dimension": dimension,
            "question": feedback.question,
            "source_type": source_type,
            "required_action": feedback.required_action,
            "queries": queries,
        }

    @staticmethod
    def _replacement_id(artifact_id: str, version: int) -> str:
        return f"{artifact_id}_v{version}"

    def _next_available_replacement_id(self, artifact_id: str) -> str:
        version = 1
        while True:
            replacement_id = self._replacement_id(artifact_id, version)
            try:
                self._artifacts.get_artifact(replacement_id)
            except ArtifactNotFoundError:
                return replacement_id
            version += 1


def _section_from_feedback(feedback: ReviewFeedback) -> str:
    for section in WriterAgent.REQUIRED_SECTIONS:
        if section.lower() in feedback.message.lower():
            return section
    return "Rework notes"


def _dimension_from_feedback(feedback: ReviewFeedback) -> str:
    text = f"{feedback.message} {feedback.required_action} {feedback.question or ''}".lower()
    if any(token in text for token in ("market share", "市场份额", "市占", "月活", "mau")):
        return "market_share"
    if any(token in text for token in ("audience", "受众", "用户画像", "demographic")):
        return "audience"
    if any(token in text for token in ("pricing", "价格", "定价")):
        return "pricing"
    return "evidence_gap"


def _targeted_queries(
    context: RunContext,
    entity: str,
    dimension: str,
    feedback: ReviewFeedback,
) -> list[str]:
    competitors = " ".join(context.request.competitors)
    base = entity
    if dimension == "market_share":
        return [
            f"{base} QuestMobile market share MAU",
            f"{base} 市场份额 月活 MAU",
            f"{base} {competitors} 免费阅读 付费阅读 市场份额".strip(),
        ]
    if dimension == "audience":
        return [
            f"{base} QuestMobile 用户画像 受众",
            f"{base} 易观 用户画像",
            f"{base} audience demographics users",
        ]
    if dimension == "pricing":
        return [
            f"{base} pricing official",
            f"{base} 价格 定价",
            f"{base} {competitors} pricing comparison".strip(),
        ]
    question = feedback.question or feedback.required_action
    return [
        f"{base} {question}",
        f"{base} {question} report",
        f"{base} {competitors} {question}".strip(),
    ]
