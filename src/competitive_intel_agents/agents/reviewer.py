"""Reviewer agent for deterministic, routable quality gates."""

from __future__ import annotations

from competitive_intel_agents.agents.base import BaseAgent
from competitive_intel_agents.agents.prompt_context import (
    coverage_payload,
    claims_map_payload,
    report_payload,
    report_history_payload,
    request_payload,
    sources_map_payload,
)
from competitive_intel_agents.artifacts import ArtifactStore
from competitive_intel_agents.journal import JournalStore
from competitive_intel_agents.models import (
    AgentRoundResult,
    AgentState,
    AnalysisClaim,
    ReportDraft,
    ReviewFeedback,
    RunContext,
    SourceArtifact,
    ReviewIssue,
)
from competitive_intel_agents.runtime.model_runtime import ModelRuntime


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

    def __init__(
        self,
        artifacts: ArtifactStore,
        journal: JournalStore | None = None,
        model_runtime: ModelRuntime | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._journal = journal
        self._model_runtime = model_runtime

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

        # Always run rule-based checks (deterministic, fast, no model needed)
        rule_feedback = self._review_report(report, claims, sources, context)

        # If model is available, also run deeper semantic review
        model_feedback: list[ReviewFeedback] = []
        if self._model_runtime is not None:
            model_feedback = self._model_review(report, claims, sources, context)

        all_feedback = _unique_feedback(rule_feedback + model_feedback)
        if all_feedback:
            return AgentRoundResult(
                completed=False,
                signals=["rework_required"],
                review_feedback=all_feedback,
            )

        return AgentRoundResult(
            completed=True,
            output_artifact_ids=[report.id],
            signals=["approved"],
        )

    def _model_review(
        self,
        report: ReportDraft,
        claims: dict[str, AnalysisClaim],
        sources: dict[str, SourceArtifact],
        context: RunContext,
    ) -> list[ReviewFeedback]:
        """Use model for deeper semantic analysis of report quality."""
        from competitive_intel_agents.prompts import AgentPromptLibrary, StructuredOutputValidator

        prompt_lib = AgentPromptLibrary()
        report_json = report_payload(report)
        claims_json = claims_map_payload(claims.values())
        sources_json = sources_map_payload(sources.values(), snippet_chars=300)
        prior_feedback = self._prior_review_feedback(context)

        task = (
            f"Review this competitive intelligence report about {context.request.company}. "
            f"Check for: unsupported claims (facts not backed by sources), "
            f"weak inferences, unclear writing, missing depth, and whether the report "
            f"directly answers every user question. "
            f"Return a JSON object with a 'feedback' array. Each feedback item must have: "
            f"'issue' (one of: missing_source, unsupported_claim, weak_inference, unclear_writing, "
            f"format_violation, missing_section), "
            f"'target_agent' (collector/analyst/writer/reviewer), "
            f"'target_artifact_id', 'message', 'required_action'. "
            f"Only report genuine issues — an empty feedback array is OK if quality is good."
        )
        model_req = prompt_lib.build(
            self.name,
            task,
            {
                "request": request_payload(context),
                "report": report_json,
                "claims": claims_json,
                "sources": sources_json,
                "coverage": coverage_payload(context, sources.values()),
                "report_history": report_history_payload(
                    self._artifacts.list_reports(context.run_id, status=None)
                ),
                "prior_review_feedback": [
                    item.to_dict() for item in prior_feedback
                ],
                "user_questions": context.request.questions,
                "competitors": context.request.competitors,
            },
        )
        resp = self._model_runtime.complete(model_req)
        if not resp.ok or not resp.parsed:
            return []

        validator = StructuredOutputValidator()
        try:
            validator.validate(self.name, resp.parsed)
        except Exception:
            return []

        feedback_payload = resp.parsed.get("feedback", [])
        if not isinstance(feedback_payload, list):
            return []

        result: list[ReviewFeedback] = []
        valid_issues = {
            "missing_source", "unsupported_claim", "weak_inference",
            "unclear_writing", "format_violation", "missing_section",
        }
        for item in feedback_payload:
            if not isinstance(item, dict):
                continue
            issue = str(item.get("issue", ""))
            if issue not in valid_issues:
                continue
            target_agent = str(item.get("target_agent", ""))
            if target_agent not in {"collector", "analyst", "writer", "reviewer"}:
                continue
            target_artifact_id = str(item.get("target_artifact_id", ""))
            message = str(item.get("message", ""))
            required_action = str(item.get("required_action", ""))
            if not target_artifact_id or not message or not required_action:
                continue
            result.append(
                ReviewFeedback(
                    issue=issue,
                    target_agent=target_agent,
                    target_artifact_id=target_artifact_id,
                    message=message,
                    required_action=required_action,
                    severity=str(item.get("severity", "blocking")),
                    blocking=bool(item.get("blocking", True)),
                    entity=item.get("entity"),
                    dimension=item.get("dimension"),
                    question=item.get("question"),
                )
            )
        return result

    def _prior_review_feedback(self, context: RunContext) -> list[ReviewFeedback]:
        if self._journal is None:
            return []
        feedback: list[ReviewFeedback] = []
        for event in self._journal.list_agent_events(context.run_id, "reviewer"):
            feedback.extend(event.review_feedback)
        return feedback

    def _review_report(
        self,
        report: ReportDraft,
        claims: dict[str, AnalysisClaim],
        sources: dict[str, SourceArtifact],
        context: RunContext,
    ) -> list[ReviewFeedback]:
        feedback: list[ReviewFeedback] = []
        coverage = coverage_payload(context, sources.values())
        feedback.extend(self._unresolved_prior_feedback(context, coverage))
        feedback.extend(self._missing_section_feedback(report))
        feedback.extend(self._unknown_claim_feedback(report, claims))
        feedback.extend(self._missing_source_feedback(report, claims, sources))
        feedback.extend(self._uncovered_source_feedback(report, claims))
        feedback.extend(self._competitive_coverage_feedback(context, report, claims, sources))
        feedback.extend(self._question_coverage_feedback(context, report, claims, sources))
        return feedback

    def _unresolved_prior_feedback(
        self,
        context: RunContext,
        coverage: dict,
    ) -> list[ReviewFeedback]:
        if self._journal is None:
            return []
        # If collector already completed its last round (sources_ready or
        # search_exhausted), don't keep flagging missing_source — the
        # collector has done all it can.
        collector_events = self._journal.list_agent_events(context.run_id, "collector")
        collector_done = any(
            sig in (ev.signals or [])
            for ev in collector_events
            for sig in ("sources_ready", "search_exhausted")
        )
        feedback: list[ReviewFeedback] = []
        for event in self._journal.list_agent_events(context.run_id, "reviewer"):
            for item in event.review_feedback:
                if not item.blocking:
                    continue
                if item.issue != "missing_source" or item.target_agent != "collector":
                    continue
                question_unresolved = bool(
                    item.question and item.question in coverage.get("missing_questions", [])
                )
                entity_unresolved = bool(
                    item.entity and item.entity in coverage.get("missing_entities", [])
                )
                generic_unresolved = not item.question and not item.entity and bool(
                    coverage.get("missing_entities") or coverage.get("missing_questions")
                )
                if not (question_unresolved or entity_unresolved or generic_unresolved):
                    continue
                # If collector has finished its work, the remaining gap is
                # for analyst/writer, not collector.
                if collector_done:
                    continue
                feedback.append(
                    ReviewFeedback(
                        issue=item.issue,
                        target_agent=item.target_agent,
                        target_artifact_id=item.target_artifact_id,
                        message=(
                            "Prior blocking reviewer feedback is still unresolved: "
                            f"{item.message}"
                        ),
                        required_action=item.required_action,
                        severity=item.severity,
                        blocking=item.blocking,
                        entity=item.entity,
                        dimension=item.dimension,
                        question=item.question,
                    )
                )
        return _unique_feedback(feedback)

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

    @staticmethod
    def _competitive_coverage_feedback(
        context: RunContext,
        report: ReportDraft,
        claims: dict[str, AnalysisClaim],
        sources: dict[str, SourceArtifact],
    ) -> list[ReviewFeedback]:
        competitors = [item for item in context.request.competitors if item]
        if not competitors:
            return []

        feedback: list[ReviewFeedback] = []
        min_sources = max(3, len(competitors) + 2)
        if len(sources) < min_sources:
            feedback.append(
                ReviewFeedback(
                    issue="missing_source",
                    target_agent="collector",
                    target_artifact_id="collector_coverage",
                    message=(
                        "Competitive report has too few active sources: "
                        f"{len(sources)} found, at least {min_sources} expected."
                    ),
                    required_action=(
                        "Collect more independent sources covering the product, "
                        "competitors, and comparison dimensions before approval."
                    ),
                    dimension="competitive coverage",
                )
            )

        for competitor in competitors:
            competitor_source_ids = {
                source_id
                for source_id, source in sources.items()
                if _source_mentions_entity(source, competitor)
            }
            if not competitor_source_ids:
                feedback.append(
                    ReviewFeedback(
                        issue="missing_source",
                        target_agent="collector",
                        target_artifact_id=f"collector_coverage:{competitor}",
                        message=f"No active source covers competitor: {competitor}.",
                        required_action=(
                            f"Collect at least one source specifically about {competitor}."
                        ),
                        entity=competitor,
                        dimension="competitor coverage",
                    )
                )
                continue

            competitor_claims = [
                claim
                for claim in claims.values()
                if competitor_source_ids.intersection(claim.source_ids)
            ]
            report_mentions_competitor_claim = any(
                claim.id in report.claim_ids for claim in competitor_claims
            )
            if not report_mentions_competitor_claim:
                feedback.append(
                    ReviewFeedback(
                        issue="unsupported_claim",
                        target_agent="analyst",
                        target_artifact_id=report.id,
                        message=(
                            f"Competitor source coverage exists for {competitor}, "
                            "but the report has no active claim using it."
                        ),
                        required_action=(
                            f"Create sourced claims about {competitor} and include "
                            "them in the report before approval."
                        ),
                        entity=competitor,
                        dimension="competitor claims",
                    )
                )

        return feedback

    @staticmethod
    def _question_coverage_feedback(
        context: RunContext,
        report: ReportDraft,
        claims: dict[str, AnalysisClaim],
        sources: dict[str, SourceArtifact],
    ) -> list[ReviewFeedback]:
        feedback: list[ReviewFeedback] = []
        report_text = " ".join(report.sections.values())
        claim_text = " ".join(
            f"{claim.text} {claim.reasoning}" for claim in claims.values()
        )
        # Exclude rework placeholders — their snippet text is the reviewer's
        # own required_action, which would falsely signal coverage.
        real_sources = {
            sid: s for sid, s in sources.items()
            if not s.url.startswith("https://rework.local/")
        }
        source_text = " ".join(
            f"{source.title} {source.snippet} {source.url}"
            for source in real_sources.values()
        )

        for question in context.request.questions:
            missing_parts = [
                part
                for part in _question_parts(question)
                if not _text_covers_topic(report_text, part)
            ]
            if not missing_parts:
                continue

            missing = ", ".join(missing_parts)
            if not all(
                _text_covers_topic(source_text, part) for part in missing_parts
            ):
                feedback.append(
                    ReviewFeedback(
                        issue="missing_source",
                        target_agent="collector",
                        target_artifact_id=f"question_coverage:{question}",
                        message=(
                            f"Report does not answer user question dimensions: {missing}."
                        ),
                        required_action=(
                            f"Collect sources that directly cover: {missing}."
                        ),
                        dimension=missing,
                        question=question,
                    )
                )
            elif not all(
                _text_covers_topic(claim_text, part) for part in missing_parts
            ):
                feedback.append(
                    ReviewFeedback(
                        issue="unsupported_claim",
                        target_agent="analyst",
                        target_artifact_id=report.id,
                        message=(
                            f"Sources exist, but claims do not address question dimensions: {missing}."
                        ),
                        required_action=(
                            f"Create sourced claims that answer: {missing}."
                        ),
                        dimension=missing,
                        question=question,
                    )
                )
            else:
                feedback.append(
                    ReviewFeedback(
                        issue="missing_section",
                        target_agent="writer",
                        target_artifact_id=report.id,
                        message=(
                            f"Claims exist, but report text does not answer question dimensions: {missing}."
                        ),
                        required_action=(
                            f"Revise the report to explicitly answer: {missing}."
                        ),
                        dimension=missing,
                        question=question,
                    )
                )
        return feedback


def _source_mentions_entity(source: SourceArtifact, entity: str) -> bool:
    if source.url.startswith("https://rework.local/"):
        return False
    metadata_entity = source.metadata.get("entity")
    if isinstance(metadata_entity, str) and metadata_entity == entity:
        return True
    haystack = " ".join([source.title, source.snippet, source.url]).lower()
    return entity.lower() in haystack


def _question_parts(question: str) -> list[str]:
    import re

    parts = [
        part.strip()
        for part in re.split(r"[,，、;；/]+", question)
        if part.strip()
    ]
    return parts or [question.strip()]


def _text_covers_topic(text: str, topic: str) -> bool:
    text_normalized = _normalize_text(text)
    topic_normalized = _normalize_text(topic)
    if not topic_normalized:
        return True
    if topic_normalized in text_normalized:
        return True

    tokens = _topic_tokens(topic)
    if not tokens:
        return False
    return all(token in text_normalized for token in tokens)


def _normalize_text(text: str) -> str:
    return "".join(text.lower().split())


def _topic_tokens(topic: str) -> list[str]:
    import re

    if any("\u4e00" <= char <= "\u9fff" for char in topic):
        return [
            part
            for part in re.split(r"[\s,，、;；/]+", topic)
            if len(part) >= 2
        ]
    stopwords = {"and", "or", "the", "a", "an", "of", "to", "in", "for"}
    return [
        token
        for token in re.findall(r"[a-z0-9]+", topic.lower())
        if len(token) > 2 and token not in stopwords
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
