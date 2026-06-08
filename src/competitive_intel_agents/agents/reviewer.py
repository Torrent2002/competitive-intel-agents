"""Reviewer agent for deterministic, routable quality gates."""

from __future__ import annotations

from competitive_intel_agents.agents.base import BaseAgent
from competitive_intel_agents.artifacts import ArtifactStore
from competitive_intel_agents.models import (
    AgentRoundResult,
    AgentState,
    AnalysisClaim,
    ReportDraft,
    ReviewFeedback,
    RunContext,
    SourceArtifact,
)


class ReviewerAgent(BaseAgent):
    """Validate report structure and evidence links without mutating artifacts."""

    name = "reviewer"

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
        report = self._artifacts.get_latest_report(context.run_id)
        if report is None:
            return AgentRoundResult(
                completed=False,
                signals=["rework_required"],
                review_feedback=[
                    ReviewFeedback(
                        issue="missing_section",
                        target_agent="writer",
                        target_artifact_id=f"report_{context.run_id}",
                        message="No active report draft is available for review.",
                        required_action="Create a report draft with all required sections.",
                    )
                ],
            )

        claims = {
            claim.id: claim for claim in self._artifacts.list_claims(context.run_id)
        }
        sources = {
            source.id: source for source in self._artifacts.list_sources(context.run_id)
        }
        feedback = self._review_report(report, claims, sources)
        if feedback:
            return AgentRoundResult(
                completed=False,
                signals=["rework_required"],
                review_feedback=feedback,
            )

        return AgentRoundResult(
            completed=True,
            output_artifact_ids=[report.id],
            signals=["approved"],
        )

    def _review_report(
        self,
        report: ReportDraft,
        claims: dict[str, AnalysisClaim],
        sources: dict[str, SourceArtifact],
    ) -> list[ReviewFeedback]:
        feedback: list[ReviewFeedback] = []
        feedback.extend(self._missing_section_feedback(report))
        feedback.extend(self._unknown_claim_feedback(report, claims))
        feedback.extend(self._missing_source_feedback(report, claims, sources))
        feedback.extend(self._uncovered_source_feedback(report, claims))
        return feedback

    def _missing_section_feedback(
        self, report: ReportDraft
    ) -> list[ReviewFeedback]:
        feedback: list[ReviewFeedback] = []
        for section in self.REQUIRED_SECTIONS:
            if not report.sections.get(section, "").strip():
                feedback.append(
                    ReviewFeedback(
                        issue="missing_section",
                        target_agent="writer",
                        target_artifact_id=report.id,
                        message=f"Report is missing the required section: {section}.",
                        required_action=f"Add a non-empty {section} section.",
                    )
                )
        return feedback

    @staticmethod
    def _unknown_claim_feedback(
        report: ReportDraft,
        claims: dict[str, AnalysisClaim],
    ) -> list[ReviewFeedback]:
        feedback: list[ReviewFeedback] = []
        for claim_id in report.claim_ids:
            if claim_id not in claims:
                feedback.append(
                    ReviewFeedback(
                        issue="unsupported_claim",
                        target_agent="analyst",
                        target_artifact_id=claim_id,
                        message=f"Report references an unknown claim: {claim_id}.",
                        required_action="Create or replace the claim with active sourced analysis.",
                    )
                )
        return feedback

    @staticmethod
    def _missing_source_feedback(
        report: ReportDraft,
        claims: dict[str, AnalysisClaim],
        sources: dict[str, SourceArtifact],
    ) -> list[ReviewFeedback]:
        feedback: list[ReviewFeedback] = []
        for source_id in report.source_ids:
            if source_id not in sources:
                feedback.append(
                    ReviewFeedback(
                        issue="missing_source",
                        target_agent="collector",
                        target_artifact_id=source_id,
                        message=f"Report references an unknown source: {source_id}.",
                        required_action="Collect and save an active source artifact for this id.",
                    )
                )
        for claim_id in report.claim_ids:
            claim = claims.get(claim_id)
            if claim is None:
                continue
            for source_id in claim.source_ids:
                if source_id not in sources:
                    feedback.append(
                        ReviewFeedback(
                            issue="missing_source",
                            target_agent="collector",
                            target_artifact_id=source_id,
                            message=(
                                f"Claim {claim_id} references an unknown source: "
                                f"{source_id}."
                            ),
                            required_action="Collect and save an active source artifact for this claim.",
                        )
                    )
        return _unique_feedback(feedback)

    @staticmethod
    def _uncovered_source_feedback(
        report: ReportDraft,
        claims: dict[str, AnalysisClaim],
    ) -> list[ReviewFeedback]:
        claim_source_ids: set[str] = set()
        for claim_id in report.claim_ids:
            claim = claims.get(claim_id)
            if claim is not None:
                claim_source_ids.update(claim.source_ids)

        uncovered_source_ids = [
            source_id
            for source_id in report.source_ids
            if source_id not in claim_source_ids
        ]
        if not uncovered_source_ids:
            return []
        return [
            ReviewFeedback(
                issue="unsupported_claim",
                target_agent="analyst",
                target_artifact_id=report.id,
                message=(
                    "Report source ids are not fully covered by referenced claims: "
                    f"{', '.join(uncovered_source_ids)}."
                ),
                required_action="Revise analysis claims so every report source supports a claim.",
            )
        ]


def _unique_feedback(feedback: list[ReviewFeedback]) -> list[ReviewFeedback]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[ReviewFeedback] = []
    for item in feedback:
        key = (item.issue, item.target_agent, item.target_artifact_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
