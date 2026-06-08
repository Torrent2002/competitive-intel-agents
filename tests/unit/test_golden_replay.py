from pathlib import Path

from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.golden import (
    ExpectedMetrics,
    GoldenReplayRunner,
    evaluate_golden_metrics,
    load_golden_cases,
)
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AnalysisClaim,
    CompetitiveIntelRequest,
    ReportDraft,
    RoundEvent,
    RunResult,
    SourceArtifact,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_loads_golden_cases_from_directory() -> None:
    cases = load_golden_cases(PROJECT_ROOT / "tests" / "golden")

    assert sorted(case.name for case in cases) == sorted([
        "case_01_single_competitor",
        "case_02_multi_competitor",
        "case_03_sparse_sources",
        "case_04_reviewer_rejection",
        "case_05_rework_success",
    ])
    first = cases[0]
    assert first.request.company in {"Figma", "Linear", "NicheCo", "Notion", "Slack"}
    assert first.expected.min_source_count >= 1


def test_golden_replay_runner_passes_fake_pipeline_case() -> None:
    runner = GoldenReplayRunner(PROJECT_ROOT / "tests" / "golden")

    summary = runner.run_all()

    assert summary.passed is True
    assert summary.total_cases == 5
    case_names = [r.case_name for r in summary.results]
    assert "case_01_single_competitor" in case_names
    assert "case_02_multi_competitor" in case_names
    assert "case_03_sparse_sources" in case_names
    assert "case_04_reviewer_rejection" in case_names
    assert "case_05_rework_success" in case_names
    for result in summary.results:
        assert result.failures == [], f"failures in {result.case_name}: {result.failures}"
        assert result.metrics["source_count"] >= 1
        assert result.metrics["claim_source_coverage_ratio"] >= 0.5


def test_golden_metrics_fail_when_required_section_missing() -> None:
    journal = InMemoryJournalStore()
    store = InMemoryArtifactStore()
    save_valid_sources_and_claims(store)
    store.save_report(
        ReportDraft(
            id="report_001",
            run_id="run_001",
            sections={"Overview": "Summary."},
            claim_ids=["claim_001"],
            source_ids=["source_001"],
        )
    )
    journal.append(
        RoundEvent(
            id="run_001:reviewer:1",
            run_id="run_001",
            agent="reviewer",
            round=1,
            decision="stop",
            signals=["approved"],
        )
    )

    result = evaluate_golden_metrics(
        journal,
        store,
        RunResult(run_id="run_001", status="approved", report_id="report_001"),
        ExpectedMetrics(required_sections=["Overview", "Pricing"]),
    )

    assert result.passed is False
    assert result.failures[0].metric == "required_sections"
    assert "Pricing" in result.failures[0].message


def test_golden_metrics_fail_when_report_has_unsupported_source() -> None:
    journal = InMemoryJournalStore()
    store = InMemoryArtifactStore()
    save_valid_sources_and_claims(store)
    store.save_report(
        ReportDraft(
            id="report_001",
            run_id="run_001",
            sections={"Overview": "Summary."},
            claim_ids=["claim_001"],
            source_ids=["source_001", "source_missing"],
        )
    )

    result = evaluate_golden_metrics(
        journal,
        store,
        RunResult(run_id="run_001", status="approved", report_id="report_001"),
        ExpectedMetrics(require_report_source_coverage=True),
    )

    assert result.passed is False
    assert result.failures[0].metric == "report_source_coverage"
    assert "source_missing" in result.failures[0].message


def test_golden_metrics_fail_when_claim_source_coverage_drops() -> None:
    journal = InMemoryJournalStore()
    store = InMemoryArtifactStore()
    store.save_claim(
        AnalysisClaim(
            id="claim_001",
            run_id="run_001",
            text="Unsupported-looking claim.",
            source_ids=["source_missing"],
        )
    )

    result = evaluate_golden_metrics(
        journal,
        store,
        RunResult(run_id="run_001", status="approved"),
        ExpectedMetrics(min_claim_source_coverage_ratio=1.0),
    )

    assert result.passed is False
    assert result.failures[0].metric == "claim_source_coverage_ratio"


def test_golden_metrics_fail_when_reviewer_was_skipped() -> None:
    journal = InMemoryJournalStore()
    store = InMemoryArtifactStore()
    journal.append(
        RoundEvent(
            id="run_001:writer:1",
            run_id="run_001",
            agent="writer",
            round=1,
            decision="stop",
            signals=["report_created"],
        )
    )

    result = evaluate_golden_metrics(
        journal,
        store,
        RunResult(run_id="run_001", status="approved"),
        ExpectedMetrics(require_reviewer=True),
    )

    assert result.passed is False
    assert result.failures[0].metric == "reviewer_required"


def test_golden_metrics_fail_when_artifact_lineage_is_broken() -> None:
    journal = InMemoryJournalStore()
    store = InMemoryArtifactStore()
    store.save_claim(
        AnalysisClaim(
            id="claim_v2",
            run_id="run_001",
            text="Looks like a replacement but lacks lineage.",
            source_ids=["source_001"],
            version=2,
        )
    )

    result = evaluate_golden_metrics(
        journal,
        store,
        RunResult(run_id="run_001", status="approved"),
        ExpectedMetrics(require_artifact_lineage=True),
    )

    assert result.passed is False
    assert result.failures[0].metric == "artifact_lineage"


def save_valid_sources_and_claims(store: InMemoryArtifactStore) -> None:
    store.save_source(
        SourceArtifact(
            id="source_001",
            run_id="run_001",
            url="https://example.com/source",
            title="Source",
            snippet="Evidence.",
        )
    )
    store.save_claim(
        AnalysisClaim(
            id="claim_001",
            run_id="run_001",
            text="Sourced claim.",
            source_ids=["source_001"],
        )
    )
