"""Writer agent for drafting source-backed reports."""

from __future__ import annotations

import sys as _sys

from competitive_intel_agents.agents.base import BaseAgent
from competitive_intel_agents.agents.prompt_context import (
    claims_list_payload,
    coverage_payload,
    filter_quality_sources,
    request_payload,
    sources_map_payload,
)
from competitive_intel_agents.artifacts import ArtifactStore
from competitive_intel_agents.memory import ConversationStore
from competitive_intel_agents.models import (
    AgentRoundResult,
    AgentState,
    AnalysisClaim,
    ReportDraft,
    RunContext,
)
from competitive_intel_agents.runtime.model_runtime import ModelRuntime


class WriterAgent(BaseAgent):
    """Turn active analysis claims into a structured report draft."""

    name = "writer"

    REQUIRED_SECTIONS = (
        "Overview",
        "Feature comparison",
        "Pricing",
        "SWOT",
        "Sources",
    )

    def __init__(
        self,
        artifacts: ArtifactStore,
        model_runtime: ModelRuntime | None = None,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._model_runtime = model_runtime
        self._conversation_store = conversation_store

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        rework_feedback = (
            context.metadata.get("rework_feedback", {}).get("writer", [])
        )
        existing_report = self._artifacts.get_latest_report(context.run_id)
        if existing_report is not None and not rework_feedback:
            return AgentRoundResult(
                completed=True,
                output_artifact_ids=[],
                signals=["report_ready"],
            )
        # Rework: reject existing report so we can create a fresh one
        if existing_report is not None and rework_feedback:
            self._artifacts.mark_rejected(
                existing_report.id, "Rewriting based on reviewer feedback"
            )

        claims = self._artifacts.list_claims(context.run_id)
        if not claims:
            return AgentRoundResult(
                completed=False,
                signals=["missing_claims"],
            )

        template_fallback = False
        if self._model_runtime is not None:
            sections = self._model_sections(context, claims)
            if not sections or all(not v or "[FAKE]" in v for v in sections.values()):
                print(
                    "[writer] WARNING: model failed, falling back to template report",
                    file=_sys.stderr,
                )
                sections = self._template_sections(context, claims)
                template_fallback = True
        else:
            print(
                "[writer] WARNING: no model runtime, using template report",
                file=_sys.stderr,
            )
            sections = self._template_sections(context, claims)
            template_fallback = True

        report = ReportDraft(
            id=self._next_report_id(context.run_id),
            run_id=context.run_id,
            sections=sections,
            claim_ids=[claim.id for claim in claims],
            source_ids=self._source_ids(claims),
        )
        self._artifacts.save_report(report)
        signals = ["report_created"]
        if template_fallback:
            signals.append("template_fallback")
        return AgentRoundResult(
            completed=True,
            output_artifact_ids=[report.id],
            signals=signals,
        )

    def _model_sections(
        self,
        context: RunContext,
        claims: list[AnalysisClaim],
    ) -> dict[str, str]:
        """Use model to compose a structured report from claims and all sources."""
        from competitive_intel_agents.prompts import AgentPromptLibrary, StructuredOutputValidator

        prompt_lib = AgentPromptLibrary()
        claims_json = claims_list_payload(claims)
        sources = filter_quality_sources(
            self._artifacts.list_sources(context.run_id)
        )

        # Writer gets larger content excerpts (8000 chars per source vs default 4000)
        # to produce deeper, more detailed analysis
        sources_payload = sources_map_payload(
            sources, snippet_chars=2000, content_excerpt_chars=8000,
        )

        # Build assessed sources context from analyst assessments
        assessed_sources = []
        for source in sources:
            assessment = source.metadata.get("analyst_assessment")
            if assessment:
                assessed_sources.append({
                    "source_id": source.id,
                    "title": source.title,
                    "url": source.url,
                    "relevance": assessment.get("relevance", "medium"),
                    "credibility": assessment.get("credibility", "medium"),
                    "covered_aspects": assessment.get("covered_aspects", []),
                    "key_insight": assessment.get("key_insight", ""),
                })

        # Read upstream agent context (analyst's notes for writer)
        upstream_contexts = self._artifacts.get_agent_contexts(context.run_id, "writer")

        questions_str = ", ".join(context.request.questions) if context.request.questions else "competitive positioning and market evidence"
        task = (
            f"You are writing a competitive intelligence report about "
            f"{context.request.company} "
            f"({'vs ' + ', '.join(context.request.competitors) if context.request.competitors else ''}).\n"
            f"The user asked: {questions_str}\n\n"
            f"Write sections: {', '.join(self.REQUIRED_SECTIONS)}.\n\n"
            f"CRITICAL RULES:\n"
            f"1. THINK CRITICALLY — do not parrot claims verbatim. Evaluate each claim's "
            f"confidence and source quality before including it.\n"
            f"2. If a claim has confidence='low' or comes from marketing material, present it "
            f"as 'X claims...' or 'according to X...', NOT as established fact.\n"
            f"3. If sources contradict each other, acknowledge the contradiction and state "
            f"what you can and cannot verify.\n"
            f"4. MARK GAPS — if important information for a section is missing from the claims, "
            f"explicitly state 'No sourced evidence available for [topic]' rather than "
            f"guessing or padding.\n"
            f"5. SYNTHESIZE — combine related claims into coherent analysis, don't just list them.\n"
            f"6. Write each section with enough depth to be genuinely useful to a decision-maker. "
            f"Aim for thorough, evidence-rich paragraphs. Include [claim_id] references inline.\n"
            f"7. The 'Sources' section should list each source with its title, url, and "
            f"a one-line quality assessment.\n"
            f"8. You have access to ALL collected sources, not just those with claims. "
            f"Sources include analyst assessments — use them to judge which sources to trust. "
            f"Draw from all available material to write a comprehensive report.\n\n"
            f"Return JSON: {{\"sections\": {{...}}, \"claim_ids\": [...], \"source_ids\": [...], "
            f"\"decisions\": [...]}}\n"
            f"Each decision: {{\"type\": str (e.g. source_deprioritized|section_gap_acknowledged|"
            f"claim_interpreted), \"target_id\": str, \"reason\": str}} — explain why you "
            f"deprioritized a source, acknowledged a gap, or interpreted a claim in a certain way."
        )
        # Include reviewer feedback for rework
        rework_feedback = context.metadata.get("rework_feedback", {}).get("writer", [])
        if rework_feedback:
            feedback_lines = "\n".join(
                f"- [{fb['severity']}] {fb['message']} (Action: {fb['required_action']})"
                for fb in rework_feedback
            )
            task += (
                f"\n\nREVIEWER FEEDBACK — you MUST address these issues:\n"
                f"{feedback_lines}\n"
                f"Rewrite the report to fix every item above."
            )
        prompt_context_data = {
            "request": request_payload(context),
            "company": context.request.company,
            "market": context.request.market,
            "competitors": context.request.competitors,
            "claims": claims_json,
            "sources": sources_payload,
            "assessed_sources": assessed_sources,
            "coverage": coverage_payload(context, sources),
            "upstream_contexts": upstream_contexts,
        }
        import json as _json
        user_content = f"{task}\n\nContext JSON:\n{_json.dumps(prompt_context_data, sort_keys=True)}"
        history = (
            self._conversation_store.get_history(context.run_id, self.name)
            if self._conversation_store
            else None
        )
        if history:
            model_req = prompt_lib.build_with_history(
                self.name, task, prompt_context_data, history=history,
            )
        else:
            model_req = prompt_lib.build(self.name, task, prompt_context_data)
        resp = self._model_runtime.complete(model_req)
        if not resp.ok or not resp.parsed:
            print(
                f"[writer] model call failed: ok={resp.ok} parsed={resp.parsed is not None} error={resp.error}",
                file=_sys.stderr,
            )
            return {}

        validator = StructuredOutputValidator()
        try:
            validator.validate(self.name, resp.parsed)
        except Exception as exc:
            print(f"[writer] validation failed: {exc}", file=_sys.stderr)
            return {}

        sections = resp.parsed.get("sections", {})
        if not isinstance(sections, dict) or not sections:
            return self._template_sections(context, claims)

        # Ensure all required sections exist
        result: dict[str, str] = {}
        for section in self.REQUIRED_SECTIONS:
            result[section] = str(sections.get(section, ""))

        # Record conversation and agent context on success
        if result and self._conversation_store:
            self._conversation_store.append_exchange(
                context.run_id, self.name, user_content, resp.content,
            )
        if result:
            decisions = resp.parsed.get("decisions", [])
            self._artifacts.save_agent_context(
                context.run_id, self.name, "reviewer",
                {
                    "decisions": decisions,
                    "sections_written": list(result.keys()),
                },
            )

        return result

    def _template_sections(
        self,
        context: RunContext,
        claims: list[AnalysisClaim],
    ) -> dict[str, str]:
        """Hardcoded section generation — fallback when no model is available."""
        claim_lines = "\n".join(self._claim_line(claim) for claim in claims)
        pricing_claims = [
            claim for claim in claims if "pricing" in claim.text.lower()
        ]
        pricing_lines = "\n".join(
            self._claim_line(claim) for claim in pricing_claims
        ) or "No sourced pricing claim is available yet."
        source_lines = "\n".join(
            f"- {source_id}" for source_id in self._source_ids(claims)
        )
        return {
            "Overview": (
                f"{context.request.company} competitive intelligence summary.\n"
                f"Sourced claims:\n{claim_lines}"
            ),
            "Feature comparison": claim_lines,
            "Pricing": pricing_lines,
            "SWOT": (
                "Sourced facts:\n"
                f"{claim_lines}\n\n"
                "Hypotheses:\n"
                "- Treat these as hypotheses until Reviewer approval."
            ),
            "Sources": source_lines,
        }

    @staticmethod
    def _claim_line(claim: AnalysisClaim) -> str:
        sources = ", ".join(claim.source_ids)
        return f"- [{claim.id}] {claim.text} (sources: {sources})"

    @staticmethod
    def _source_ids(claims: list[AnalysisClaim]) -> list[str]:
        source_ids: list[str] = []
        for claim in claims:
            for source_id in claim.source_ids:
                if source_id not in source_ids:
                    source_ids.append(source_id)
        return source_ids

    def _next_report_id(self, run_id: str) -> str:
        reports = self._artifacts.list_reports(run_id, status=None)
        if not reports:
            return f"report_{run_id}_001"
        next_index = len(reports) + 1
        return f"report_{run_id}_{next_index:03d}"
