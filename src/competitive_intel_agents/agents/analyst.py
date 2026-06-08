"""Analyst agent for turning sources into sourced claims."""

from __future__ import annotations

from competitive_intel_agents.agents.base import BaseAgent
from competitive_intel_agents.artifacts import ArtifactStore
from competitive_intel_agents.models import (
    AgentRoundResult,
    AgentState,
    AnalysisClaim,
    RunContext,
    SourceArtifact,
)


class AnalystAgent(BaseAgent):
    """Create source-backed analysis claims from collected sources."""

    name = "analyst"

    def __init__(self, artifacts: ArtifactStore, target_claims: int = 2) -> None:
        self._artifacts = artifacts
        self._target_claims = target_claims

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        sources = self._artifacts.list_sources(context.run_id)
        if not sources:
            return AgentRoundResult(
                completed=False,
                signals=["missing_sources"],
            )

        existing_claims = self._artifacts.list_claims(context.run_id)
        if len(existing_claims) >= self._target_claims:
            return AgentRoundResult(
                completed=True,
                output_artifact_ids=[],
                signals=["claims_ready"],
            )

        claimed_source_ids = {
            source_id
            for claim in existing_claims
            for source_id in claim.source_ids
        }
        saved_ids: list[str] = []
        for source in sources:
            if len(existing_claims) + len(saved_ids) >= self._target_claims:
                break
            if source.id in claimed_source_ids:
                continue
            claim = self._claim_from_source(context, source)
            self._artifacts.save_claim(claim)
            saved_ids.append(claim.id)
            claimed_source_ids.add(source.id)

        claims_after_save = self._artifacts.list_claims(context.run_id)
        completed = len(claims_after_save) >= self._target_claims
        if saved_ids:
            signals = ["claims_created"]
        elif completed:
            signals = ["claims_ready"]
        else:
            signals = ["insufficient_sources"]
        return AgentRoundResult(
            completed=completed,
            output_artifact_ids=saved_ids,
            signals=signals,
        )

    def _claim_from_source(
        self,
        context: RunContext,
        source: SourceArtifact,
    ) -> AnalysisClaim:
        return AnalysisClaim(
            id=self._next_claim_id(context.run_id),
            run_id=context.run_id,
            text=self._claim_text(context, source),
            source_ids=[source.id],
            confidence="medium",
            reasoning=f"Derived from source {source.id}: {source.title}",
        )

    def _next_claim_id(self, run_id: str) -> str:
        next_index = len(self._artifacts.list_claims(run_id)) + 1
        return f"claim_{run_id}_{next_index:03d}"

    @staticmethod
    def _claim_text(context: RunContext, source: SourceArtifact) -> str:
        subject = context.request.company
        evidence = source.snippet or source.title or source.url
        return f"{subject} evidence from {source.title}: {evidence}"
