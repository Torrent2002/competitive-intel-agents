from competitive_intel_agents.agents import BaseAgent
from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.models import (
    AgentResult,
    CompetitiveIntelRequest,
    ReportDraft,
    RoundEvent,
    ReviewFeedback,
)
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.orchestrator import Orchestrator


def make_request() -> CompetitiveIntelRequest:
    return CompetitiveIntelRequest(
        company="ACME",
        market="collaboration software",
        competitors=["Globex"],
        questions=["pricing"],
    )


def make_single_company_request() -> CompetitiveIntelRequest:
    return CompetitiveIntelRequest(
        company="ACME",
        market="collaboration software",
        questions=["pricing"],
    )


def test_orchestrator_runs_default_dag_end_to_end_with_fake_tools() -> None:
    orchestrator = Orchestrator(run_id_factory=lambda: "run_001")

    result = orchestrator.run(make_single_company_request())

    assert result.status == "approved"
    assert result.run_id == "run_001"
    assert result.report_id == "report_run_001_001"
    assert result.review_feedback == []

    events = orchestrator.journal.list_run_events("run_001")
    first_seen_order = list(dict.fromkeys(event.agent for event in events))
    assert first_seen_order == ["collector", "analyst", "writer", "reviewer"]
    assert events[-1].agent == "reviewer"
    assert events[-1].decision == "stop"
    assert events[-1].signals == ["approved"]

    source_ids = [source.id for source in orchestrator.artifacts.list_sources("run_001")]
    assert len(source_ids) >= 2
    assert all(sid.startswith("source_run_001_") for sid in source_ids)
    assert [claim.id for claim in orchestrator.artifacts.list_claims("run_001")] == [
        "claim_run_001_001",
        "claim_run_001_002",
    ]
    assert orchestrator.artifacts.get_latest_report("run_001").id == "report_run_001_001"


def test_orchestrator_creates_run_context_with_role_bounded_profiles() -> None:
    orchestrator = Orchestrator(run_id_factory=lambda: "run_001")

    orchestrator.run(make_request())

    context = orchestrator.last_context
    assert context is not None
    assert context.agent_profiles["collector"].allowed_tools == [
        "web_search",
        "web_fetch",
    ]
    assert context.agent_profiles["analyst"].allowed_tools == []
    assert context.agent_profiles["writer"].allowed_tools == []
    assert context.agent_profiles["reviewer"].allowed_tools == []


class AbortingHarness:
    def __init__(self) -> None:
        self.agents: list[str] = []

    def run_agent(self, context, agent: BaseAgent) -> AgentResult:
        self.agents.append(agent.name)
        return AgentResult(agent=agent.name, decision="abort", rounds=1)


def test_orchestrator_aborts_when_harness_aborts() -> None:
    harness = AbortingHarness()
    orchestrator = Orchestrator(
        harness=harness,
        run_id_factory=lambda: "run_abort",
    )

    result = orchestrator.run(make_request())

    assert result.status == "aborted"
    assert result.run_id == "run_abort"
    assert result.report_id is None
    assert result.error == "collector aborted"
    assert harness.agents == ["collector"]


class ReworkHarness:
    def __init__(self) -> None:
        self.agents: list[str] = []

    def run_agent(self, context, agent: BaseAgent) -> AgentResult:
        self.agents.append(agent.name)
        if agent.name == "reviewer":
            return AgentResult(
                agent="reviewer",
                decision="rework",
                rounds=1,
                review_feedback=[
                    ReviewFeedback(
                        issue="missing_source",
                        target_agent="collector",
                        target_artifact_id="source_missing",
                        message="Missing source.",
                        required_action="Collect a replacement source.",
                    )
                ],
            )
        return AgentResult(agent=agent.name, decision="stop", rounds=1)


def test_orchestrator_returns_needs_rework_with_reviewer_feedback() -> None:
    harness = ReworkHarness()
    orchestrator = Orchestrator(
        harness=harness,
        run_id_factory=lambda: "run_rework",
    )

    result = orchestrator.run(make_request())

    assert result.status == "needs_rework"
    assert result.review_feedback[0].target_agent == "collector"
    assert harness.agents == ["collector", "analyst", "writer", "reviewer"]


def test_orchestrator_can_apply_rework_until_reviewer_approves() -> None:
    class OneShotWriterFeedbackHarness:
        def __init__(self) -> None:
            self.reviewer_calls = 0

        def run_agent(self, context, agent: BaseAgent) -> AgentResult:
            if agent.name == "reviewer":
                self.reviewer_calls += 1
                if self.reviewer_calls == 1:
                    return AgentResult(
                        agent="reviewer",
                        decision="rework",
                        rounds=1,
                        review_feedback=[
                            ReviewFeedback(
                                issue="missing_section",
                                target_agent="writer",
                                target_artifact_id="report_missing",
                                message="Missing Pricing.",
                                required_action="Add Pricing.",
                            )
                        ],
                    )
            return AgentResult(agent=agent.name, decision="stop", rounds=1)

    harness = OneShotWriterFeedbackHarness()
    orchestrator = Orchestrator(
        harness=harness,
        enable_rework=True,
        run_id_factory=lambda: "run_integrated_rework",
    )

    result = orchestrator.run(make_request())

    assert result.status == "approved"
    assert result.review_feedback == []
    assert harness.reviewer_calls == 2


class CoveragePartialHarness:
    def __init__(self, journal: InMemoryJournalStore) -> None:
        self.journal = journal
        self.agents: list[str] = []

    def run_agent(self, context, agent: BaseAgent) -> AgentResult:
        self.agents.append(agent.name)
        signals = ["coverage_partial"] if agent.name == "collector" else []
        self.journal.append(
            RoundEvent(
                id=f"{context.run_id}:{agent.name}:{len(self.agents)}",
                run_id=context.run_id,
                agent=agent.name,
                round=1,
                decision="stop",
                signals=signals,
            )
        )
        return AgentResult(agent=agent.name, decision="stop", rounds=1)


def test_orchestrator_skips_writer_when_analyst_sees_partial_coverage() -> None:
    journal = InMemoryJournalStore()
    harness = CoveragePartialHarness(journal)
    orchestrator = Orchestrator(
        journal=journal,
        harness=harness,
        run_id_factory=lambda: "run_coverage_rework",
    )

    result = orchestrator.run(make_request())

    assert result.status == "needs_rework"
    assert result.report_id is None
    assert result.review_feedback[0].target_agent == "collector"
    assert result.review_feedback[0].issue == "missing_source"
    assert harness.agents == ["collector", "analyst"]


def test_orchestrator_recollects_before_writer_when_integrated_rework_enabled() -> None:
    journal = InMemoryJournalStore()
    harness = CoveragePartialHarness(journal)
    orchestrator = Orchestrator(
        journal=journal,
        harness=harness,
        enable_rework=True,
        run_id_factory=lambda: "run_coverage_rework",
    )

    result = orchestrator.run(make_request())

    assert result.status == "approved"
    assert harness.agents == [
        "collector",
        "analyst",
        "collector",
        "analyst",
        "writer",
        "reviewer",
    ]


def test_orchestrator_returns_rework_failed_after_max_attempts() -> None:
    class PersistentWriterFeedbackHarness:
        def __init__(self) -> None:
            self.reviewer_calls = 0

        def run_agent(self, context, agent: BaseAgent) -> AgentResult:
            if agent.name == "reviewer":
                self.reviewer_calls += 1
                return AgentResult(
                    agent="reviewer",
                    decision="rework",
                    rounds=1,
                    review_feedback=[
                        ReviewFeedback(
                            issue="missing_section",
                            target_agent="writer",
                            target_artifact_id="report_missing",
                            message="Missing Pricing.",
                            required_action="Add Pricing.",
                        )
                    ],
                )
            return AgentResult(agent=agent.name, decision="stop", rounds=1)

    harness = PersistentWriterFeedbackHarness()
    orchestrator = Orchestrator(
        harness=harness,
        enable_rework=True,
        max_rework_attempts=1,
        run_id_factory=lambda: "run_rework_failed",
    )

    result = orchestrator.run(make_request())

    assert result.status == "rework_failed"
    assert result.review_feedback[0].target_agent == "writer"


def test_orchestrator_prioritizes_upstream_feedback_when_multiple_targets_exist() -> None:
    class MixedFeedbackHarness:
        def __init__(self) -> None:
            self.agents: list[str] = []
            self.reviewer_calls = 0

        def run_agent(self, context, agent: BaseAgent) -> AgentResult:
            self.agents.append(agent.name)
            if agent.name == "reviewer":
                self.reviewer_calls += 1
                if self.reviewer_calls == 1:
                    return AgentResult(
                        agent="reviewer",
                        decision="rework",
                        rounds=1,
                        review_feedback=[
                            ReviewFeedback(
                                issue="missing_section",
                                target_agent="writer",
                                target_artifact_id="report_missing",
                                message="Missing Pricing.",
                                required_action="Add Pricing.",
                            ),
                            ReviewFeedback(
                                issue="missing_source",
                                target_agent="collector",
                                target_artifact_id="source_missing",
                                message="Missing competitor pricing source.",
                                required_action="Collect competitor pricing evidence.",
                            ),
                        ],
                    )
            return AgentResult(agent=agent.name, decision="stop", rounds=1)

    harness = MixedFeedbackHarness()
    orchestrator = Orchestrator(
        harness=harness,
        enable_rework=True,
        run_id_factory=lambda: "run_mixed_rework",
    )

    result = orchestrator.run(make_request())

    assert result.status == "approved"
    assert harness.agents == [
        "collector",
        "analyst",
        "writer",
        "reviewer",
        "collector",
        "analyst",
        "writer",
        "reviewer",
    ]


def test_orchestrator_reports_needs_more_evidence_for_persistent_collector_blockers() -> None:
    harness = ReworkHarness()
    orchestrator = Orchestrator(
        harness=harness,
        enable_rework=True,
        max_rework_attempts=1,
        run_id_factory=lambda: "run_needs_more_evidence",
    )

    result = orchestrator.run(make_request())

    assert result.status == "needs_more_evidence"
    assert result.error == "max_rework_attempts_exceeded"
    assert result.review_feedback[0].issue == "missing_source"
    assert result.review_feedback[0].target_agent == "collector"


def test_orchestrator_returns_approved_with_caveats_when_report_survives() -> None:
    """When non-collector blockers persist after the rework budget but a
    deliverable report exists, the run should ship as approved_with_caveats
    with the residual feedback exposed via RunResult.caveats."""

    artifacts = InMemoryArtifactStore()

    class CaveatHarness:
        def __init__(self) -> None:
            self.reviewer_calls = 0
            self.writer_calls = 0

        def run_agent(self, context, agent: BaseAgent) -> AgentResult:
            if agent.name == "writer":
                self.writer_calls += 1
                report_id = f"report_caveat_{self.writer_calls:03d}"
                # Each writer round persists a fresh report id. The
                # real writer behaves the same — it does not edit the
                # superseded artifact in place.
                report = ReportDraft(
                    id=report_id,
                    run_id=context.run_id,
                    sections={"Summary": f"ACME ships v{self.writer_calls}."},
                    claim_ids=[],
                    source_ids=[],
                )
                artifacts.save_report(report)
                return AgentResult(
                    agent="writer",
                    decision="stop",
                    rounds=1,
                    output_artifact_ids=[report.id],
                )
            if agent.name == "reviewer":
                self.reviewer_calls += 1
                # Always target an artifact id that does NOT exist in
                # the store, so ReworkLoop's prepare_changes path takes
                # the ArtifactNotFoundError branch (no version bump,
                # no DuplicateArtifactError) on every iteration. The
                # blocker keeps surfacing → orchestrator exhausts the
                # rework budget → caveats path engages.
                return AgentResult(
                    agent="reviewer",
                    decision="rework",
                    rounds=1,
                    review_feedback=[
                        ReviewFeedback(
                            issue="unsupported_claim",
                            target_agent="analyst",
                            target_artifact_id="report_caveat_phantom",
                            message="Headcount figure not supported by sources.",
                            required_action="Drop or back the headcount claim.",
                        )
                    ],
                )
            return AgentResult(agent=agent.name, decision="stop", rounds=1)

    harness = CaveatHarness()
    orchestrator = Orchestrator(
        artifacts=artifacts,
        harness=harness,
        enable_rework=True,
        max_rework_attempts=2,
        run_id_factory=lambda: "run_with_caveats",
    )

    result = orchestrator.run(make_request())

    assert result.status == "approved_with_caveats"
    # Latest report is the most recent writer output.
    assert result.report_id is not None
    assert result.report_id.startswith("report_caveat_")
    assert result.error == "max_rework_attempts_exceeded"
    # Residual feedback is moved to caveats — review_feedback stays empty
    # so downstream code that branches on a non-empty review_feedback
    # list does not treat the run as a hard failure.
    assert result.review_feedback == []
    assert len(result.caveats) == 1
    assert result.caveats[0].issue == "unsupported_claim"
    assert result.caveats[0].target_agent == "analyst"


def test_orchestrator_keeps_rework_failed_when_no_report_was_produced() -> None:
    """If non-collector blockers persist AND no report exists, there is
    nothing to deliver — the run must remain rework_failed rather than
    silently turning into approved_with_caveats."""

    class NoReportHarness:
        def run_agent(self, context, agent: BaseAgent) -> AgentResult:
            if agent.name == "reviewer":
                return AgentResult(
                    agent="reviewer",
                    decision="rework",
                    rounds=1,
                    review_feedback=[
                        ReviewFeedback(
                            issue="missing_section",
                            target_agent="writer",
                            target_artifact_id="report_missing",
                            message="Report omits Pricing.",
                            required_action="Add a Pricing section.",
                        )
                    ],
                )
            # Writer/analyst/collector all stop without producing
            # artifacts — no report is ever persisted.
            return AgentResult(agent=agent.name, decision="stop", rounds=1)

    orchestrator = Orchestrator(
        harness=NoReportHarness(),
        enable_rework=True,
        max_rework_attempts=1,
        run_id_factory=lambda: "run_no_report",
    )

    result = orchestrator.run(make_request())

    assert result.status == "rework_failed"
    assert result.report_id is None
    assert result.caveats == []
    # The blocker stays on review_feedback for diagnostics.
    assert result.review_feedback and result.review_feedback[0].issue == "missing_section"


# ── Global wall-clock timeout (Module 33) ──────────────────────


def test_orchestrator_returns_aborted_when_timeout_before_any_report() -> None:
    """When the deadline expires before any report is produced, the run
    must abort cleanly rather than continue burning budget."""

    # time_provider yields strictly increasing values: t=0 at __init__,
    # t=10000 at the first deadline check inside run(). Anything past
    # the deadline (max_wall_time=1.0 → deadline=1.0) returns the
    # timeout result on the very first agent boundary.
    ticks = iter([0.0, 10_000.0, 10_001.0, 10_002.0])

    class NoOpHarness:
        def run_agent(self, context, agent):
            return AgentResult(agent=agent.name, decision="stop", rounds=1)

    orchestrator = Orchestrator(
        harness=NoOpHarness(),
        max_wall_time=1.0,
        time_provider=lambda: next(ticks),
        run_id_factory=lambda: "run_timeout_no_report",
    )

    result = orchestrator.run(make_request())

    assert result.status == "aborted"
    assert result.error == "global_timeout"
    assert result.report_id is None
    assert result.caveats == []


def test_orchestrator_returns_caveats_when_timeout_after_report_exists() -> None:
    """If a report has already been written when the deadline trips, the
    run should ship as approved_with_caveats so the user keeps the
    partial work plus an explicit timeout caveat."""

    artifacts = InMemoryArtifactStore()

    class WriterRecordingHarness:
        """Persists a report on the writer round, then lets time march
        past the deadline before the next agent boundary."""

        def __init__(self) -> None:
            self.calls: list[str] = []

        def run_agent(self, context, agent):
            self.calls.append(agent.name)
            if agent.name == "writer":
                report = ReportDraft(
                    id=f"report_timeout_{context.run_id}_001",
                    run_id=context.run_id,
                    sections={"Summary": "Partial deliverable."},
                    claim_ids=[],
                    source_ids=[],
                )
                artifacts.save_report(report)
                return AgentResult(
                    agent="writer",
                    decision="stop",
                    rounds=1,
                    output_artifact_ids=[report.id],
                )
            return AgentResult(agent=agent.name, decision="stop", rounds=1)

    # First two ticks: __init__ (t=0) and first deadline check at the
    # collector boundary (t=0.5, deadline=10.0 not yet reached).
    # Then time leaps past the deadline before the reviewer boundary.
    ticks = iter([0.0, 0.5, 0.6, 0.7, 1000.0, 1000.1])
    harness = WriterRecordingHarness()
    orchestrator = Orchestrator(
        artifacts=artifacts,
        harness=harness,
        max_wall_time=10.0,
        time_provider=lambda: next(ticks),
        run_id_factory=lambda: "run_timeout_with_report",
    )

    result = orchestrator.run(make_request())

    assert result.status == "approved_with_caveats"
    assert result.error == "global_timeout"
    assert result.report_id is not None
    assert result.report_id.startswith("report_timeout_")
    assert result.review_feedback == []
    assert len(result.caveats) == 1
    assert result.caveats[0].issue == "format_violation"
    assert "wall-clock budget" in result.caveats[0].message
    # Reviewer never ran because the deadline tripped between writer and reviewer.
    assert "reviewer" not in harness.calls


def test_orchestrator_no_timeout_when_max_wall_time_is_none() -> None:
    """Passing ``max_wall_time=None`` disables the deadline entirely —
    used by every existing harness-driven test that doesn't model time."""

    orchestrator = Orchestrator(
        max_wall_time=None,
        run_id_factory=lambda: "run_no_deadline",
    )

    result = orchestrator.run(make_single_company_request())

    # Same outcome as the canonical end-to-end test — the deadline
    # logic must not change behavior when disabled.
    assert result.status == "approved"
    assert result.error is None
