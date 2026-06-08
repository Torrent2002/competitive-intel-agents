"""Writer agent for drafting source-backed reports."""

from __future__ import annotations

from competitive_intel_agents.agents.base import BaseAgent
from competitive_intel_agents.artifacts import ArtifactStore
from competitive_intel_agents.models import (
    AgentRoundResult,
    AgentState,
    AnalysisClaim,
    ReportDraft,
    RunContext,
)


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

    def __init__(self, artifacts: ArtifactStore) -> None:
        self._artifacts = artifacts

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

        report = ReportDraft(
            id=self._next_report_id(context.run_id),
            run_id=context.run_id,
            sections=self._sections(context, claims),
            claim_ids=[claim.id for claim in claims],
            source_ids=self._source_ids(claims),
        )
        self._artifacts.save_report(report)
        return AgentRoundResult(
            completed=True,
            output_artifact_ids=[report.id],
            signals=["report_created"],
        )

    def _sections(
        self,
        context: RunContext,
        claims: list[AnalysisClaim],
    ) -> dict[str, str]:
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
        existing = self._artifacts.get_latest_report(run_id)
        if existing is None:
            return f"report_{run_id}_001"
        return f"report_{run_id}_{existing.version + 1:03d}"
