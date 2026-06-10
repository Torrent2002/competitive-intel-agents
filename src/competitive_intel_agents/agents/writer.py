"""Writer agent for drafting source-backed reports."""

from __future__ import annotations

from competitive_intel_agents.agents.base import BaseAgent
from competitive_intel_agents.agents.prompt_context import (
    claims_list_payload,
    coverage_payload,
    request_payload,
    sources_map_payload,
)
from competitive_intel_agents.artifacts import ArtifactStore
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
    ) -> None:
        self._artifacts = artifacts
        self._model_runtime = model_runtime

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        existing_report = self._artifacts.get_latest_report(context.run_id)
        if existing_report is not None:
            return AgentRoundResult(
                completed=True,
                output_artifact_ids=[],
                signals=["report_ready"],
            )

        claims = self._artifacts.list_claims(context.run_id)
        if not claims:
            return AgentRoundResult(
                completed=False,
                signals=["missing_claims"],
            )

        if self._model_runtime is not None:
            sections = self._model_sections(context, claims)
        else:
            sections = self._template_sections(context, claims)

        report = ReportDraft(
            id=self._next_report_id(context.run_id),
            run_id=context.run_id,
            sections=sections,
            claim_ids=[claim.id for claim in claims],
            source_ids=self._source_ids(claims),
        )
        self._artifacts.save_report(report)
        return AgentRoundResult(
            completed=True,
            output_artifact_ids=[report.id],
            signals=["report_created"],
        )

    def _model_sections(
        self,
        context: RunContext,
        claims: list[AnalysisClaim],
    ) -> dict[str, str]:
        """Use model to compose a structured report from claims."""
        from competitive_intel_agents.prompts import AgentPromptLibrary, StructuredOutputValidator

        prompt_lib = AgentPromptLibrary()
        claims_json = claims_list_payload(claims)
        claim_source_ids = {
            source_id
            for claim in claims
            for source_id in claim.source_ids
        }
        sources = [
            source
            for source in self._artifacts.list_sources(context.run_id)
            if source.id in claim_source_ids
        ]

        task = (
            f"Write a competitive intelligence report about {context.request.company} "
            f"based on the provided claims. Return a JSON object with a 'sections' object "
            f"containing these keys: {', '.join(self.REQUIRED_SECTIONS)}. "
            f"Each section value should be 2-4 paragraphs of substantive analysis. "
            f"Do NOT fabricate facts not present in the claims. "
            f"Include claim references like [claim_id] in the text. "
            f"Also include 'claim_ids' (list) and 'source_ids' (list) in the JSON."
        )
        model_req = prompt_lib.build(
            self.name,
            task,
            {
                "request": request_payload(context),
                "company": context.request.company,
                "market": context.request.market,
                "competitors": context.request.competitors,
                "claims": claims_json,
                "sources": sources_map_payload(sources),
                "coverage": coverage_payload(context, sources),
            },
        )
        resp = self._model_runtime.complete(model_req)
        if not resp.ok or not resp.parsed:
            return self._template_sections(context, claims)

        validator = StructuredOutputValidator()
        try:
            validator.validate(self.name, resp.parsed)
        except Exception:
            return self._template_sections(context, claims)

        sections = resp.parsed.get("sections", {})
        if not isinstance(sections, dict) or not sections:
            return self._template_sections(context, claims)

        # Ensure all required sections exist
        result: dict[str, str] = {}
        for section in self.REQUIRED_SECTIONS:
            result[section] = str(sections.get(section, ""))
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
