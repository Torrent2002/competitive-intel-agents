"""Golden replay runner and workflow-quality metrics."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from competitive_intel_agents.artifacts import ArtifactNotFoundError, ArtifactStore
from competitive_intel_agents.models import CompetitiveIntelRequest, RunResult
from competitive_intel_agents.orchestrator import Orchestrator
from competitive_intel_agents.journal import JournalStore


@dataclass(frozen=True)
class ExpectedMetrics:
    required_sections: list[str] = field(default_factory=list)
    min_source_count: int = 0
    min_claim_count: int = 0
    min_claim_source_coverage_ratio: float = 0.0
    require_report_source_coverage: bool = False
    max_reviewer_rejections: int | None = None
    max_total_rounds: int | None = None
    max_tool_calls: int | None = None
    terminal_status: str | None = None
    terminal_decision: str | None = None
    require_reviewer: bool = False
    max_rework_attempts: int | None = None
    require_artifact_lineage: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExpectedMetrics":
        return cls(**payload)


@dataclass(frozen=True)
class GoldenCase:
    name: str
    request: CompetitiveIntelRequest
    expected: ExpectedMetrics
    path: Path


@dataclass(frozen=True)
class MetricFailure:
    metric: str
    expected: object
    actual: object
    message: str


@dataclass(frozen=True)
class GoldenCaseResult:
    case_name: str
    passed: bool
    metrics: dict[str, object]
    failures: list[MetricFailure] = field(default_factory=list)


@dataclass(frozen=True)
class GoldenReplaySummary:
    total_cases: int
    results: list[GoldenCaseResult]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)


def load_golden_cases(root: str | Path) -> list[GoldenCase]:
    root_path = Path(root)
    cases: list[GoldenCase] = []
    for case_dir in sorted(path for path in root_path.iterdir() if path.is_dir()):
        input_path = case_dir / "input.json"
        expected_path = case_dir / "expected.json"
        if not input_path.exists() or not expected_path.exists():
            continue
        request = CompetitiveIntelRequest.from_dict(
            json.loads(input_path.read_text(encoding="utf-8"))
        )
        expected = ExpectedMetrics.from_dict(
            json.loads(expected_path.read_text(encoding="utf-8"))
        )
        cases.append(
            GoldenCase(
                name=case_dir.name,
                request=request,
                expected=expected,
                path=case_dir,
            )
        )
    return cases


class GoldenReplayRunner:
    """Run deterministic golden cases through the local fake pipeline."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def run_all(self) -> GoldenReplaySummary:
        results = [self.run_case(case) for case in load_golden_cases(self._root)]
        return GoldenReplaySummary(total_cases=len(results), results=results)

    def run_case(self, case: GoldenCase) -> GoldenCaseResult:
        orchestrator = Orchestrator(
            enable_rework=True,
            run_id_factory=lambda: f"golden_{case.name}",
        )
        run_result = orchestrator.run(case.request)
        return evaluate_golden_metrics(
            orchestrator.journal,
            orchestrator.artifacts,
            run_result,
            case.expected,
            case_name=case.name,
        )


def evaluate_golden_metrics(
    journal: JournalStore,
    artifacts: ArtifactStore,
    run_result: RunResult,
    expected: ExpectedMetrics,
    case_name: str = "manual",
) -> GoldenCaseResult:
    run_id = run_result.run_id
    events = journal.list_run_events(run_id)
    report = (
        artifacts.get_artifact(run_result.report_id)
        if run_result.report_id is not None
        else artifacts.get_latest_report(run_id)
    )
    sources = artifacts.list_sources(run_id)
    claims = artifacts.list_claims(run_id)
    all_artifacts = [
        *artifacts.list_sources(run_id, status=None),
        *artifacts.list_claims(run_id, status=None),
        *artifacts.list_reports(run_id, status=None),
    ]
    metrics = {
        "source_count": len(sources),
        "claim_count": len(claims),
        "claim_source_coverage_ratio": _claim_source_coverage_ratio(claims, sources),
        "report_source_coverage": _report_source_coverage(report, sources),
        "reviewer_rejections": sum(
            len(event.review_feedback) for event in events if event.agent == "reviewer"
        ),
        "total_rounds": len(events),
        "tool_calls": sum(len(event.tool_calls) for event in events),
        "terminal_status": run_result.status,
        "terminal_decision": events[-1].decision if events else None,
        "reviewer_ran": any(event.agent == "reviewer" for event in events),
        "rework_attempts": sum(1 for event in events if event.decision == "rework"),
        "artifact_lineage_valid": _artifact_lineage_valid(all_artifacts, artifacts),
    }
    failures = _evaluate_failures(expected, metrics, report)
    return GoldenCaseResult(
        case_name=case_name,
        passed=not failures,
        metrics=metrics,
        failures=failures,
    )


def _evaluate_failures(
    expected: ExpectedMetrics,
    metrics: dict[str, object],
    report,
) -> list[MetricFailure]:
    failures: list[MetricFailure] = []

    if expected.required_sections:
        actual_sections = set(report.sections) if report is not None else set()
        missing = [
            section
            for section in expected.required_sections
            if section not in actual_sections
        ]
        if missing:
            failures.append(
                MetricFailure(
                    "required_sections",
                    expected.required_sections,
                    sorted(actual_sections),
                    f"missing required sections: {', '.join(missing)}",
                )
            )
    _at_least(failures, "source_count", expected.min_source_count, metrics)
    _at_least(failures, "claim_count", expected.min_claim_count, metrics)
    _at_least(
        failures,
        "claim_source_coverage_ratio",
        expected.min_claim_source_coverage_ratio,
        metrics,
    )
    if (
        expected.require_report_source_coverage
        and metrics["report_source_coverage"] is not True
    ):
        failures.append(
            MetricFailure(
                "report_source_coverage",
                True,
                metrics["report_source_coverage"],
                f"report has missing source ids: {metrics['report_source_coverage']}",
            )
        )
    _at_most_optional(failures, "reviewer_rejections", expected.max_reviewer_rejections, metrics)
    _at_most_optional(failures, "total_rounds", expected.max_total_rounds, metrics)
    _at_most_optional(failures, "tool_calls", expected.max_tool_calls, metrics)
    _equals_optional(failures, "terminal_status", expected.terminal_status, metrics)
    _equals_optional(failures, "terminal_decision", expected.terminal_decision, metrics)
    if expected.require_reviewer and metrics["reviewer_ran"] is not True:
        failures.append(
            MetricFailure(
                "reviewer_required",
                True,
                metrics["reviewer_ran"],
                "run completed without reviewer events",
            )
        )
    _at_most_optional(failures, "rework_attempts", expected.max_rework_attempts, metrics)
    if expected.require_artifact_lineage and metrics["artifact_lineage_valid"] is not True:
        failures.append(
            MetricFailure(
                "artifact_lineage",
                True,
                metrics["artifact_lineage_valid"],
                "replacement artifact lineage is invalid",
            )
        )
    return failures


def _at_least(
    failures: list[MetricFailure],
    metric: str,
    expected_min: int | float,
    metrics: dict[str, object],
) -> None:
    if metrics[metric] < expected_min:
        failures.append(
            MetricFailure(
                metric,
                f">= {expected_min}",
                metrics[metric],
                f"{metric} dropped below expected minimum",
            )
        )


def _at_most_optional(
    failures: list[MetricFailure],
    metric: str,
    expected_max: int | None,
    metrics: dict[str, object],
) -> None:
    if expected_max is None:
        return
    if metrics[metric] > expected_max:
        failures.append(
            MetricFailure(
                metric,
                f"<= {expected_max}",
                metrics[metric],
                f"{metric} exceeded expected maximum",
            )
        )


def _equals_optional(
    failures: list[MetricFailure],
    metric: str,
    expected_value: str | None,
    metrics: dict[str, object],
) -> None:
    if expected_value is None:
        return
    if metrics[metric] != expected_value:
        failures.append(
            MetricFailure(
                metric,
                expected_value,
                metrics[metric],
                f"{metric} changed",
            )
        )


def _claim_source_coverage_ratio(claims, sources) -> float:
    if not claims:
        return 0.0
    source_ids = {source.id for source in sources}
    covered = sum(
        1 for claim in claims if claim.source_ids and set(claim.source_ids) <= source_ids
    )
    return covered / len(claims)


def _report_source_coverage(report, sources) -> bool | list[str]:
    if report is None:
        return []
    source_ids = {source.id for source in sources}
    missing = [source_id for source_id in report.source_ids if source_id not in source_ids]
    return True if not missing else missing


def _artifact_lineage_valid(all_artifacts, artifacts: ArtifactStore) -> bool:
    by_id = {artifact.id: artifact for artifact in all_artifacts}
    for artifact in all_artifacts:
        if artifact.version <= 1:
            continue
        if not artifact.supersedes_id or artifact.supersedes_id not in by_id:
            return False
        old = by_id[artifact.supersedes_id]
        if old.run_id != artifact.run_id:
            return False
        if old.version >= artifact.version:
            return False
        try:
            current_old = artifacts.get_artifact(old.id)
        except ArtifactNotFoundError:
            return False
        if current_old.status not in {"superseded", "rejected"}:
            return False
    return True


__all__ = [
    "ExpectedMetrics",
    "GoldenCase",
    "GoldenCaseResult",
    "GoldenReplayRunner",
    "GoldenReplaySummary",
    "MetricFailure",
    "evaluate_golden_metrics",
    "load_golden_cases",
]
