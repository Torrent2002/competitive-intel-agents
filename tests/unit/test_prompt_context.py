from competitive_intel_agents.agents.prompt_context import coverage_payload
from competitive_intel_agents.models import (
    AgentProfile,
    CompetitiveIntelRequest,
    RunContext,
    SourceArtifact,
)


def make_context() -> RunContext:
    return RunContext(
        run_id="run_coverage",
        request=CompetitiveIntelRequest(
            company="番茄小说",
            market="在线阅读",
            competitors=["起点阅读"],
            questions=["比较免费阅读模式和付费阅读模式对用户规模的影响"],
        ),
        agent_profiles={
            "collector": AgentProfile(
                agent="collector",
                max_rounds=10,
                allowed_tools=["web_search", "web_fetch"],
            )
        },
    )


def test_coverage_payload_builds_dynamic_evidence_needs_from_request() -> None:
    source = SourceArtifact(
        id="source_001",
        run_id="run_coverage",
        url="https://example.com/report",
        title="番茄小说免费阅读报告",
        snippet="番茄小说通过免费阅读和广告变现推动用户规模增长。",
        metadata={
            "entity": "番茄小说",
            "entity_role": "self",
            "covered_dimensions": ["business_model", "audience"],
            "extract_quality": "good",
            "source_score": 52,
        },
    )

    payload = coverage_payload(make_context(), [source])

    needs = payload["evidence_needs"]
    assert needs
    assert any(
        need["subject"] == "番茄小说"
        and "免费阅读" in need["need"]
        and need["status"] == "covered"
        and need["source_ids"] == ["source_001"]
        for need in needs
    )
    assert any(
        need["subject"] == "起点阅读"
        and need["status"] == "missing"
        for need in needs
    )
    assert payload["weak_evidence_needs"] == []


def test_coverage_payload_marks_low_quality_matching_sources_as_weak() -> None:
    source = SourceArtifact(
        id="source_weak",
        run_id="run_coverage",
        url="https://example.com/app",
        title="App shell",
        snippet="需要启用JavaScript。",
        metadata={
            "entity": "番茄小说",
            "covered_dimensions": ["business_model"],
            "extract_quality": "js_required",
            "source_score": -10,
        },
    )

    payload = coverage_payload(make_context(), [source])

    assert any(
        need["subject"] == "番茄小说"
        and "免费阅读" in need["need"]
        and need["status"] == "weak"
        and need["source_ids"] == ["source_weak"]
        for need in payload["evidence_needs"]
    )
    assert payload["weak_evidence_needs"]
