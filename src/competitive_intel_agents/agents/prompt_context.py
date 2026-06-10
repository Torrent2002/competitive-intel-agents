"""Shared context serializers for model-backed agent prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from competitive_intel_agents.models import (
    AnalysisClaim,
    CompetitiveIntelRequest,
    ReportDraft,
    RunContext,
    SourceArtifact,
)


def request_payload(context: RunContext) -> dict:
    request = context.request
    return {
        "company": request.company,
        "market": request.market,
        "competitors": list(request.competitors),
        "questions": list(request.questions),
    }


def source_payload(
    source: SourceArtifact,
    snippet_chars: int = 1000,
    content_excerpt_chars: int = 4000,
) -> dict:
    metadata = dict(source.metadata)
    content_excerpt = _content_excerpt(
        metadata.get("content_ref"),
        max_chars=content_excerpt_chars,
    )
    return {
        "id": source.id,
        "title": source.title,
        "url": source.url,
        "snippet": source.snippet[:snippet_chars],
        "source_type": metadata.get("source_type", source.source_type),
        "entity": metadata.get("entity"),
        "entity_role": metadata.get("entity_role"),
        "dimension": metadata.get("dimension"),
        "content_ref": metadata.get("content_ref"),
        "content_hash": metadata.get("content_hash"),
        "char_count": metadata.get("char_count"),
        "summary": metadata.get("summary"),
        "preview": metadata.get("preview"),
        "content_excerpt": content_excerpt,
        "metadata": metadata,
    }


def sources_list_payload(
    sources: Iterable[SourceArtifact],
    snippet_chars: int = 1000,
) -> list[dict]:
    return [source_payload(source, snippet_chars=snippet_chars) for source in sources]


def sources_map_payload(
    sources: Iterable[SourceArtifact],
    snippet_chars: int = 1000,
) -> dict[str, dict]:
    return {
        source.id: source_payload(source, snippet_chars=snippet_chars)
        for source in sources
    }


def claim_payload(claim: AnalysisClaim) -> dict:
    return {
        "id": claim.id,
        "text": claim.text,
        "source_ids": list(claim.source_ids),
        "confidence": claim.confidence,
        "reasoning": claim.reasoning,
    }


def claims_list_payload(claims: Iterable[AnalysisClaim]) -> list[dict]:
    return [claim_payload(claim) for claim in claims]


def claims_map_payload(claims: Iterable[AnalysisClaim]) -> dict[str, dict]:
    return {claim.id: claim_payload(claim) for claim in claims}


def report_payload(report: ReportDraft) -> dict:
    return {
        "id": report.id,
        "status": report.status,
        "version": report.version,
        "supersedes_id": report.supersedes_id,
        "sections": dict(report.sections),
        "claim_ids": list(report.claim_ids),
        "source_ids": list(report.source_ids),
    }


def report_history_payload(reports: Iterable[ReportDraft]) -> list[dict]:
    return [report_payload(report) for report in reports]


def coverage_payload(
    context: RunContext,
    sources: Iterable[SourceArtifact],
) -> dict:
    source_list = list(sources)
    request = context.request
    required_entities = _required_entities(request)
    covered_entities = {
        entity
        for source in source_list
        if isinstance((entity := source.metadata.get("entity")), str) and entity
    }
    missing_entities = [
        item["entity"]
        for item in required_entities
        if item["entity"] not in covered_entities
    ]

    covered_dimensions = {
        dimension
        for source in source_list
        if isinstance((dimension := source.metadata.get("dimension")), str)
        and dimension
    }
    missing_questions = [
        question
        for question in request.questions
        if not _question_has_dimension_match(question, covered_dimensions)
    ]

    return {
        "source_count": len(source_list),
        "required_entities": required_entities,
        "covered_entities": sorted(covered_entities),
        "missing_entities": missing_entities,
        "requested_questions": list(request.questions),
        "covered_dimensions": sorted(covered_dimensions),
        "missing_questions": missing_questions,
    }


def _required_entities(request: CompetitiveIntelRequest) -> list[dict[str, str]]:
    entities = [{"entity": request.company, "role": "self"}]
    entities.extend(
        {"entity": competitor, "role": "competitor"}
        for competitor in request.competitors
        if competitor
    )
    return entities


def _question_has_dimension_match(
    question: str,
    covered_dimensions: set[str],
) -> bool:
    if not question:
        return True
    normalized_question = question.lower()
    for dimension in covered_dimensions:
        normalized_dimension = dimension.lower()
        if normalized_dimension in normalized_question:
            return True
        if normalized_question in normalized_dimension:
            return True
    return False


def _content_excerpt(content_ref: object, max_chars: int) -> str:
    if not isinstance(content_ref, str) or not content_ref.startswith("file:"):
        return ""
    path = Path(content_ref.removeprefix("file:"))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return text[:max_chars]
