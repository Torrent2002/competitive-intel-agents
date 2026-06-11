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

    covered_dimensions = _covered_dimensions(source_list)
    missing_questions = [
        question
        for question in request.questions
        if not _question_has_dimension_match(question, covered_dimensions)
    ]
    evidence_needs = _evidence_needs(request, source_list)

    return {
        "source_count": len(source_list),
        "required_entities": required_entities,
        "covered_entities": sorted(covered_entities),
        "missing_entities": missing_entities,
        "requested_questions": list(request.questions),
        "covered_dimensions": sorted(covered_dimensions),
        "missing_questions": missing_questions,
        "evidence_needs": evidence_needs,
        "missing_evidence_needs": [
            need for need in evidence_needs if need["status"] == "missing"
        ],
        "weak_evidence_needs": [
            need for need in evidence_needs if need["status"] == "weak"
        ],
    }


def _required_entities(request: CompetitiveIntelRequest) -> list[dict[str, str]]:
    entities = [{"entity": request.company, "role": "self"}]
    entities.extend(
        {"entity": competitor, "role": "competitor"}
        for competitor in request.competitors
        if competitor
    )
    return entities


def _covered_dimensions(sources: list[SourceArtifact]) -> set[str]:
    dimensions: set[str] = set()
    for source in sources:
        metadata = source.metadata
        dimension = metadata.get("dimension")
        if isinstance(dimension, str) and dimension:
            dimensions.add(dimension)
        covered = metadata.get("covered_dimensions")
        if isinstance(covered, list):
            dimensions.update(item for item in covered if isinstance(item, str) and item)
    return dimensions


def _evidence_needs(
    request: CompetitiveIntelRequest,
    sources: list[SourceArtifact],
) -> list[dict]:
    subjects = _required_entities(request)
    needs = _need_templates(request)
    items: list[dict] = []
    for subject in subjects:
        for index, need in enumerate(needs, start=1):
            matching = [
                source
                for source in sources
                if _source_matches_need(source, subject["entity"], need["dimensions"])
            ]
            strong = [source for source in matching if _source_quality(source) == "strong"]
            weak = [source for source in matching if _source_quality(source) == "weak"]
            if strong:
                status = "covered"
                source_ids = [source.id for source in strong]
            elif weak:
                status = "weak"
                source_ids = [source.id for source in weak]
            else:
                status = "missing"
                source_ids = []
            items.append(
                {
                    "id": f"need_{len(items) + 1:03d}",
                    "subject": subject["entity"],
                    "subject_role": subject["role"],
                    "need": need["need"],
                    "why": need["why"],
                    "question": need["question"],
                    "dimensions": need["dimensions"],
                    "evidence_type": need["evidence_type"],
                    "status": status,
                    "source_ids": source_ids,
                    "weak_source_ids": [source.id for source in weak],
                    "slot": f"{subject['entity']}::{index}",
                }
            )
    return items


def _need_templates(request: CompetitiveIntelRequest) -> list[dict]:
    questions = request.questions or ["core product, competitive positioning, and evidence"]
    templates: list[dict] = []
    for question in questions:
        normalized = question.lower()
        dimensions = _question_dimensions(question)
        if any(token in normalized for token in ("免费", "付费", "商业模式", "广告", "订阅", "business model")):
            templates.append(
                {
                    "need": "免费阅读/付费阅读模式与变现方式",
                    "why": "用户问题要求比较商业模式和竞争差异",
                    "question": question,
                    "dimensions": sorted(set(["business_model", *dimensions])),
                    "evidence_type": "official_or_industry",
                }
            )
        if any(token in normalized for token in ("用户规模", "月活", "mau", "受众", "用户画像", "audience")):
            templates.append(
                {
                    "need": "用户规模、受众画像或增长影响",
                    "why": "用户问题要求判断市场影响和目标人群",
                    "question": question,
                    "dimensions": sorted(set(["audience", "market_share", *dimensions])),
                    "evidence_type": "data_provider_or_industry",
                }
            )
        if not templates or not any(item["question"] == question for item in templates):
            templates.append(
                {
                    "need": question,
                    "why": "用户显式提出的问题需要对应证据",
                    "question": question,
                    "dimensions": dimensions or ["evidence_gap"],
                    "evidence_type": "official_or_industry",
                }
            )
    return _dedupe_needs(templates)


def _question_dimensions(question: str) -> list[str]:
    normalized = question.lower()
    dimensions: list[str] = []
    checks = {
        "business_model": ("免费", "付费", "商业模式", "广告", "订阅", "business model"),
        "audience": ("受众", "用户画像", "用户规模", "audience", "demographic"),
        "market_share": ("市场份额", "市占", "月活", "mau", "排名", "market share"),
        "pricing": ("价格", "定价", "pricing"),
        "features": ("功能", "feature", "能力"),
        "comparison": ("对比", "竞争", "差异", "vs", "compare"),
    }
    for dimension, keywords in checks.items():
        if any(keyword in normalized for keyword in keywords):
            dimensions.append(dimension)
    return dimensions


def _dedupe_needs(needs: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for need in needs:
        key = (need["need"], need["question"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(need)
    return deduped


def _source_matches_need(
    source: SourceArtifact,
    subject: str,
    dimensions: list[str],
) -> bool:
    metadata = source.metadata
    entity = metadata.get("entity")
    if isinstance(entity, str) and entity and entity != subject:
        return False
    haystack = " ".join(
        str(part)
        for part in (
            source.title,
            source.snippet,
            metadata.get("summary", ""),
            metadata.get("preview", ""),
        )
    ).lower()
    if subject.lower() not in haystack and entity != subject:
        return False
    source_dimensions = set()
    dimension = metadata.get("dimension")
    if isinstance(dimension, str):
        source_dimensions.add(dimension)
    covered = metadata.get("covered_dimensions")
    if isinstance(covered, list):
        source_dimensions.update(item for item in covered if isinstance(item, str))
    return bool(source_dimensions.intersection(dimensions))


def _source_quality(source: SourceArtifact) -> str:
    metadata = source.metadata
    if metadata.get("extract_quality") in {"empty", "js_required"}:
        return "weak"
    score = metadata.get("source_score")
    if isinstance(score, (int, float)) and score < 0:
        return "weak"
    return "strong"


def filter_quality_sources(
    sources: Iterable[SourceArtifact],
    min_quality: str = "medium",
) -> list[SourceArtifact]:
    """Filter out low-quality sources.

    Quality levels: "strong" (extract_quality=good, non-negative score),
    "medium" (extract_quality=partial), "weak" (empty/js_required/negative score).
    min_quality="medium" drops weak sources; min_quality="strong" keeps only strong.
    """
    result: list[SourceArtifact] = []
    for source in sources:
        metadata = source.metadata
        eq = metadata.get("extract_quality", "")
        score = metadata.get("source_score")

        if eq in ("js_required", "empty"):
            continue
        if isinstance(score, (int, float)) and score < 0:
            continue
        if min_quality == "strong" and eq != "good":
            continue
        result.append(source)
    return result


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
