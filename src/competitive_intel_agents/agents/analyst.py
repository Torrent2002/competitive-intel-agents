"""Analyst agent for turning sources into sourced claims."""

from __future__ import annotations

import json

from competitive_intel_agents.agents.base import BaseAgent
from competitive_intel_agents.agents.prompt_context import (
    coverage_payload,
    filter_quality_sources,
    request_payload,
    sources_list_payload,
)
from competitive_intel_agents.artifacts import ArtifactStore
from competitive_intel_agents.memory import ConversationStore, InMemoryConversationStore
from competitive_intel_agents.models import (
    AgentRoundResult,
    AgentState,
    AnalysisClaim,
    RunContext,
    SourceArtifact,
)
from competitive_intel_agents.runtime.model_runtime import ModelRuntime
from competitive_intel_agents.logging import get_logger

logger = get_logger(__name__)


class AnalystAgent(BaseAgent):
    """Create source-backed analysis claims from collected sources."""

    name = "analyst"

    def __init__(
        self,
        artifacts: ArtifactStore,
        target_claims: int = 2,
        model_runtime: ModelRuntime | None = None,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._target_claims = target_claims
        self._model_runtime = model_runtime
        self._conversation_store = conversation_store

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
        template_fallback = False
        if self._model_runtime is not None:
            saved_ids = self._model_claims(context, sources, existing_claims)
            if not saved_ids:
                logger.warning(
                    "model failed, falling back to template claims",
                    extra={"run_id": context.run_id, "agent": "analyst"},
                )
                saved_ids = self._template_claims(context, sources, existing_claims)
                template_fallback = True
        else:
            logger.warning(
                "no model runtime, using template claims",
                extra={"run_id": context.run_id, "agent": "analyst"},
            )
            saved_ids = self._template_claims(context, sources, existing_claims)
            template_fallback = True

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
        if template_fallback:
            signals.append("template_fallback")
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
        """Use model to assess sources and generate sourced claims."""
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

        prompt_sources = filter_quality_sources(unclaimed_sources)
        if not prompt_sources:
            return []
        sources_json = sources_list_payload(prompt_sources, snippet_chars=500)

        questions_str = ", ".join(context.request.questions) if context.request.questions else "core product, competitive positioning, and market evidence"
        task = (
            f"You are a competitive intelligence analyst. Your job is to evaluate "
            f"each source and extract PRECISE, VERIFIABLE factual claims about "
            f"{context.request.company} and its competitors "
            f"({', '.join(context.request.competitors) if context.request.competitors else 'none specified'}).\n\n"
            f"The user wants to answer these questions: {questions_str}\n\n"
            f"STEP 1 — SOURCE ASSESSMENT: Evaluate EVERY source. For each source, output:\n"
            f"- source_id: the source's id\n"
            f"- relevance: 'high' | 'medium' | 'low' (how relevant to the analysis questions)\n"
            f"- credibility: 'high' | 'medium' | 'low' (official source = high, media = medium, blog/forum = low)\n"
            f"- covered_aspects: list of topics this source covers (e.g. ['features', 'pricing'])\n"
            f"- key_insight: one sentence summarizing the most valuable information in this source\n"
            f"- claim_worthy: true if this source contains extractable factual claims\n\n"
            f"STEP 2 — CLAIM EXTRACTION: Extract factual claims. RULES:\n"
            f"1. Each claim must be a SINGLE specific, factual statement — not vague summaries.\n"
            f"2. Prefer claims that directly address the user's questions above.\n"
            f"3. If a source makes a marketing claim ('leading platform', 'best-in-class'), "
            f"distill the FACT behind it (e.g. 'X claims Y million users as of Z') or label "
            f"confidence as 'low'.\n"
            f"4. Cross-reference: if two sources disagree, note it in reasoning.\n"
            f"5. confidence='high' ONLY when multiple sources agree or the claim comes from "
            f"an official primary source. confidence='low' for unverified or marketing claims.\n"
            f"6. Do NOT generate claims about topics with no supporting evidence.\n"
            f"7. SOURCE DIVERSITY: Extract at least 1 claim from EVERY source where claim_worthy=true. "
            f"Do NOT concentrate all claims on a single source.\n\n"
            f"Return JSON: {{\"source_assessments\": [...], \"claims\": [...], \"decisions\": [...]}}\n"
            f"Each claim: {{\"text\": str, \"source_ids\": [str], \"confidence\": str, \"reasoning\": str}}\n"
            f"Each decision: {{\"type\": str (e.g. source_skipped|claim_not_extracted|focus_chosen), "
            f"\"target_id\": str, \"reason\": str}} — explain why you skipped a source, "
            f"did not extract a claim, or chose a focus area."
        )
        # Include reviewer feedback for rework
        rework_feedback = context.metadata.get("rework_feedback", {}).get("analyst", [])
        if rework_feedback:
            feedback_lines = "\n".join(
                f"- [{fb['severity']}] {fb['message']} (Action: {fb['required_action']})"
                for fb in rework_feedback
            )
            task += (
                f"\n\nREVIEWER FEEDBACK — you MUST address these issues:\n"
                f"{feedback_lines}\n"
                f"Focus your claim extraction on fixing the gaps identified above."
            )
        prompt_context = {
            "request": request_payload(context),
            "company": context.request.company,
            "competitors": context.request.competitors,
            "sources": sources_json,
            "coverage": coverage_payload(context, sources),
        }
        user_content = f"{task}\n\nContext JSON:\n{json.dumps(prompt_context, sort_keys=True)}"
        history = (
            self._conversation_store.get_history(context.run_id, self.name)
            if self._conversation_store
            else None
        )
        if history:
            model_req = prompt_lib.build_with_history(
                self.name, task, prompt_context, history=history,
            )
        else:
            model_req = prompt_lib.build(self.name, task, prompt_context)
        resp = self._model_runtime.complete(model_req)
        if not resp.ok or not resp.parsed:
            logger.error(
                "analyst model call failed",
                extra={
                    "run_id": context.run_id,
                    "agent": "analyst",
                    "ok": resp.ok,
                    "parsed": resp.parsed is not None,
                    "error": resp.error,
                },
            )
            return []

        validator = StructuredOutputValidator()
        try:
            validator.validate(self.name, resp.parsed)
        except Exception as exc:
            logger.error(
                "analyst output validation failed",
                extra={"run_id": context.run_id, "agent": "analyst", "error": str(exc)},
            )
            return []

        # Save source assessments to source metadata
        source_assessments = resp.parsed.get("source_assessments", [])
        for assessment in source_assessments:
            if not isinstance(assessment, dict):
                continue
            sid = assessment.get("source_id", "")
            if not sid:
                continue
            self._artifacts.update_source_metadata(sid, {
                "analyst_assessment": {
                    "relevance": assessment.get("relevance", "medium"),
                    "credibility": assessment.get("credibility", "medium"),
                    "covered_aspects": assessment.get("covered_aspects", []),
                    "key_insight": assessment.get("key_insight", ""),
                }
            })

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

        # Record conversation exchange for multi-turn memory
        if saved_ids and self._conversation_store:
            self._conversation_store.append_exchange(
                context.run_id, self.name, user_content, resp.content,
            )

        # Write agent context for downstream agents (P2 inter-agent messaging)
        if saved_ids:
            assessments_summary = []
            for assessment in source_assessments:
                if isinstance(assessment, dict) and assessment.get("source_id"):
                    assessments_summary.append({
                        "source_id": assessment["source_id"],
                        "relevance": assessment.get("relevance", "medium"),
                        "credibility": assessment.get("credibility", "medium"),
                        "claim_worthy": assessment.get("claim_worthy", True),
                    })
            decisions = resp.parsed.get("decisions", [])
            self._artifacts.save_agent_context(
                context.run_id, self.name, "writer",
                {
                    "source_assessments_summary": assessments_summary,
                    "decisions": decisions,
                    "claims_count": len(saved_ids),
                },
            )
            self._artifacts.save_agent_context(
                context.run_id, self.name, "reviewer",
                {
                    "source_assessments_summary": assessments_summary,
                    "decisions": decisions,
                },
            )

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
