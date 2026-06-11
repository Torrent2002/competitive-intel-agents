"""Analyst agent for turning sources into sourced claims."""

from __future__ import annotations

import json

from competitive_intel_agents.agents.base import BaseAgent
from competitive_intel_agents.agents.prompt_context import (
    coverage_payload,
    request_payload,
    sources_list_payload,
)
from competitive_intel_agents.artifacts import ArtifactStore
from competitive_intel_agents.models import (
    AgentRoundResult,
    AgentState,
    AnalysisClaim,
    RunContext,
    SourceArtifact,
)
from competitive_intel_agents.runtime.model_runtime import ModelRuntime


class AnalystAgent(BaseAgent):
    """Create source-backed analysis claims from collected sources."""

    name = "analyst"

    def __init__(
        self,
        artifacts: ArtifactStore,
        target_claims: int = 2,
        model_runtime: ModelRuntime | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._target_claims = target_claims
        self._model_runtime = model_runtime

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        sources = self._artifacts.list_sources(context.run_id)
        if not sources:
            return AgentRoundResult(
                completed=True,
                signals=["missing_sources"],
            )

        existing_claims = self._artifacts.list_claims(context.run_id)
        target_claims = self._effective_target_claims(context, sources)
        if (
            len(existing_claims) >= target_claims
            and not self._unclaimed_required_source_ids(context, sources, existing_claims)
        ):
            return AgentRoundResult(
                completed=True,
                output_artifact_ids=[],
                signals=["claims_ready"],
            )

        saved_ids: list[str] = []
        if self._model_runtime is not None:
            saved_ids = self._model_claims(context, sources, existing_claims)
        else:
            saved_ids = self._template_claims(context, sources, existing_claims)

        claims_after_save = self._artifacts.list_claims(context.run_id)
        completed = (
            len(claims_after_save) >= target_claims
            and not self._unclaimed_required_source_ids(
                context,
                sources,
                claims_after_save,
            )
        )
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

    def _model_claims(
        self,
        context: RunContext,
        sources: list[SourceArtifact],
        existing_claims,
    ) -> list[str]:
        """Use model to generate sourced claims from available sources."""
        from competitive_intel_agents.prompts import AgentPromptLibrary, StructuredOutputValidator

        prompt_lib = AgentPromptLibrary()
        claimed_source_ids = {
            source_id
            for claim in existing_claims
            for source_id in claim.source_ids
        }
        unclaimed_sources = [s for s in sources if s.id not in claimed_source_ids]
        if not unclaimed_sources:
            return []

        prompt_sources = unclaimed_sources[:5]
        sources_json = sources_list_payload(prompt_sources, snippet_chars=500)

        task = (
            f"Analyze the following sources about {context.request.company} "
            f"and produce 2-3 factual claims. Each claim MUST reference at least one "
            f"source_id from the provided sources. "
            f"Return a JSON object with a 'claims' array where each claim has: "
            f"'text' (one sentence factual claim), 'source_ids' (list of source id strings), "
            f"'confidence' (high/medium/low), 'reasoning' (one sentence)."
        )
        model_req = prompt_lib.build(
            self.name,
            task,
            {
                "request": request_payload(context),
                "company": context.request.company,
                "competitors": context.request.competitors,
                "sources": sources_json,
                "coverage": coverage_payload(context, sources),
            },
        )
        resp = self._model_runtime.complete(model_req)
        if not resp.ok or not resp.parsed:
            return self._template_claims(context, sources, existing_claims)

        validator = StructuredOutputValidator()
        try:
            validator.validate(self.name, resp.parsed)
        except Exception:
            return self._template_claims(context, sources, existing_claims)

        claims_payload = resp.parsed.get("claims", [])
        saved_ids: list[str] = []
        claimed_source_ids = set(claimed_source_ids)
        for item in claims_payload:
            if not isinstance(item, dict):
                continue
            source_ids = item.get("source_ids", [])
            if not source_ids:
                continue
            valid_sids = [sid for sid in source_ids if sid in {s.id for s in sources}]
            if not valid_sids:
                continue
            claim = AnalysisClaim(
                id=self._next_claim_id(context.run_id),
                run_id=context.run_id,
                text=str(item.get("text", "")),
                source_ids=valid_sids,
                confidence=str(item.get("confidence", "medium")),
                reasoning=str(item.get("reasoning", "")),
            )
            try:
                self._artifacts.save_claim(claim)
                saved_ids.append(claim.id)
                for sid in valid_sids:
                    claimed_source_ids.add(sid)
            except Exception:
                continue

        return saved_ids

    def _template_claims(
        self,
        context: RunContext,
        sources: list[SourceArtifact],
        existing_claims,
    ) -> list[str]:
        """Hardcoded claim generation — fallback when no model is available."""
        claimed_source_ids = {
            source_id
            for claim in existing_claims
            for source_id in claim.source_ids
        }
        saved_ids: list[str] = []
        ordered_sources = self._prioritized_sources(context, sources, existing_claims)
        for source in ordered_sources:
            target_claims = self._effective_target_claims(context, sources)
            if (
                len(existing_claims) + len(saved_ids) >= target_claims
                and source.id not in self._unclaimed_required_source_ids(
                    context,
                    sources,
                    [*existing_claims, *self._claims_by_id(context.run_id, saved_ids)],
                )
            ):
                break
            if source.id in claimed_source_ids:
                continue
            claim = self._claim_from_source(context, source)
            self._artifacts.save_claim(claim)
            saved_ids.append(claim.id)
            claimed_source_ids.add(source.id)
        return saved_ids

    def _prioritized_sources(
        self,
        context: RunContext,
        sources: list[SourceArtifact],
        existing_claims: list[AnalysisClaim],
    ) -> list[SourceArtifact]:
        unclaimed_required = self._unclaimed_required_source_ids(
            context,
            sources,
            existing_claims,
        )
        return sorted(
            sources,
            key=lambda source: 0 if source.id in unclaimed_required else 1,
        )

    def _effective_target_claims(
        self,
        context: RunContext,
        sources: list[SourceArtifact],
    ) -> int:
        required_entities = 1 + len(context.request.competitors)
        return max(self._target_claims, required_entities)

    def _unclaimed_required_source_ids(
        self,
        context: RunContext,
        sources: list[SourceArtifact],
        claims: list[AnalysisClaim],
    ) -> set[str]:
        claimed_source_ids = {
            source_id
            for claim in claims
            for source_id in claim.source_ids
        }
        required_entities = {context.request.company, *context.request.competitors}
        return {
            source.id
            for source in sources
            if source.id not in claimed_source_ids
            and source.metadata.get("entity") in required_entities
        }

    def _claims_by_id(self, run_id: str, claim_ids: list[str]) -> list[AnalysisClaim]:
        claims = {
            claim.id: claim
            for claim in self._artifacts.list_claims(run_id)
        }
        return [claims[claim_id] for claim_id in claim_ids if claim_id in claims]

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
        next_index = len(self._artifacts.list_claims(run_id, status=None)) + 1
        return f"claim_{run_id}_{next_index:03d}"

    @staticmethod
    def _claim_text(context: RunContext, source: SourceArtifact) -> str:
        subject = context.request.company
        evidence = source.snippet or source.title or source.url
        return f"{subject} evidence from {source.title}: {evidence}"
