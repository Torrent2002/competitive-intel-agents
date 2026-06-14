import json

from competitive_intel_agents.agents import ReviewerAgent
from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.harness import InMemoryCheckpointStore, RuntimeHarness
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AgentProfile,
    AgentState,
    AnalysisClaim,
    CompetitiveIntelRequest,
    ModelResponse,
    ReportDraft,
    ReviewFeedback,
    RunContext,
    RoundEvent,
    SourceArtifact,
)
from competitive_intel_agents.runtime import ToolRuntime


def context_payload(model_request):
    return json.loads(model_request.messages[1]["content"].split("Context JSON:\n", 1)[1])


class CapturingModelRuntime:
    def __init__(self, parsed):
        self.parsed = parsed
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ModelResponse(ok=True, parsed=self.parsed)


def make_context(run_id: str = "run_001") -> RunContext:
    return RunContext(
        run_id=run_id,
        request=CompetitiveIntelRequest(company="Acme", competitors=["Beta"]),
        agent_profiles={
            "reviewer": AgentProfile(
                agent="reviewer",
                max_rounds=2,
                allowed_tools=[],
            )
        },
    )


def make_question_context(question: str, run_id: str = "run_001") -> RunContext:
    return RunContext(
        run_id=run_id,
        request=CompetitiveIntelRequest(
            company="Acme",
            competitors=["Beta"],
            questions=[question],
        ),
        agent_profiles={
            "reviewer": AgentProfile(
                agent="reviewer",
                max_rounds=2,
                allowed_tools=[],
            )
        },
    )


def save_source(
    store: InMemoryArtifactStore,
    source_id: str = "source_001",
    entity: str | None = "Acme",
    metadata: dict | None = None,
) -> None:
    source_metadata = dict(metadata or {})
    if entity:
        source_metadata["entity"] = entity
    store.save_source(
        SourceArtifact(
            id=source_id,
            run_id="run_001",
            url=f"https://example.com/{source_id}",
            title="Example source",
            snippet="Evidence snippet.",
            metadata=source_metadata,
        )
    )


def save_claim(
    store: InMemoryArtifactStore,
    claim_id: str = "claim_001",
    source_ids: list[str] | None = None,
) -> None:
    store.save_claim(
        AnalysisClaim(
            id=claim_id,
            run_id="run_001",
            text="Beta has a published team plan.",
            source_ids=source_ids or ["source_001"],
            confidence="high",
            reasoning="The source describes the plan.",
        )
    )


def save_report(
    store: InMemoryArtifactStore,
    report_id: str = "report_run_001_001",
    sections: dict[str, str] | None = None,
    claim_ids: list[str] | None = None,
    source_ids: list[str] | None = None,
    version: int = 1,
    status: str = "active",
    supersedes_id: str | None = None,
) -> None:
    store.save_report(
        ReportDraft(
            id=report_id,
            run_id="run_001",
            status=status,
            version=version,
            supersedes_id=supersedes_id,
            sections=sections
            or {
                "Overview": "Summary.",
                "Feature comparison": "Comparison.",
                "Pricing": "Pricing.",
                "SWOT": "SWOT.",
                "Sources": "- source_001",
            },
            claim_ids=claim_ids or ["claim_001"],
            source_ids=source_ids or ["source_001"],
        )
    )


def test_reviewer_approves_fully_sourced_report() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001", entity="Acme")
    save_source(store, "source_002", entity="Beta")
    save_source(store, "source_003", entity="Acme")
    save_claim(store, "claim_001", source_ids=["source_001"])
    save_claim(store, "claim_002", source_ids=["source_002"])
    save_report(
        store,
        claim_ids=["claim_001", "claim_002"],
        source_ids=["source_001", "source_002"],
    )

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is True
    assert result.signals == ["approved"]
    assert result.output_artifact_ids == ["report_run_001_001"]
    assert result.tool_calls == []
    assert result.review_feedback == []


def test_reviewer_model_context_includes_request_coverage_gaps_and_source_refs() -> None:
    store = InMemoryArtifactStore()
    save_source(
        store,
        "source_001",
        entity="Acme",
        metadata={
            "dimension": "pricing",
            "content_ref": "content/run_001/source_001.txt",
            "content_hash": "abc123",
            "char_count": 4096,
            "summary": "Acme pricing summary",
            "source_type": "official",
        },
    )
    save_claim(store, "claim_001", source_ids=["source_001"])
    save_report(store, claim_ids=["claim_001"], source_ids=["source_001"])
    runtime = CapturingModelRuntime({"feedback": []})
    reviewer = ReviewerAgent(store, model_runtime=runtime)

    reviewer.run_round(
        make_question_context("pricing"),
        AgentState(agent="reviewer"),
    )

    payload = context_payload(runtime.requests[0])
    assert payload["request"]["company"] == "Acme"
    assert payload["request"]["competitors"] == ["Beta"]
    assert payload["request"]["questions"] == ["pricing"]
    assert payload["coverage"]["missing_entities"] == ["Beta"]
    assert payload["coverage"]["source_count"] == 1
    assert payload["sources"]["source_001"]["content_ref"] == "content/run_001/source_001.txt"
    assert payload["sources"]["source_001"]["metadata"]["char_count"] == 4096


def test_reviewer_model_context_includes_report_history_and_prior_feedback() -> None:
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    save_source(store, "source_001", entity="Acme")
    save_source(store, "source_002", entity="Beta")
    save_claim(store, "claim_001", source_ids=["source_001"])
    save_claim(store, "claim_002", source_ids=["source_002"])
    save_report(
        store,
        report_id="report_run_001_001",
        claim_ids=["claim_001"],
        source_ids=["source_001"],
    )
    save_report(
        store,
        report_id="report_run_001_002",
        claim_ids=["claim_001", "claim_002"],
        source_ids=["source_001", "source_002"],
        version=2,
        supersedes_id="report_run_001_001",
    )
    store.mark_superseded("report_run_001_001", "report_run_001_002")
    prior_feedback = ReviewFeedback(
        issue="missing_section",
        target_agent="writer",
        target_artifact_id="report_run_001_001",
        message="Pricing section was missing.",
        required_action="Add pricing analysis.",
    )
    journal.append(
        RoundEvent(
            id="run_001:reviewer:1",
            run_id="run_001",
            agent="reviewer",
            round=1,
            decision="rework",
            review_feedback=[prior_feedback],
        )
    )
    runtime = CapturingModelRuntime({"feedback": []})
    reviewer = ReviewerAgent(store, journal=journal, model_runtime=runtime)

    reviewer.run_round(make_context(), AgentState(agent="reviewer"))

    payload = context_payload(runtime.requests[0])
    assert [item["id"] for item in payload["report_history"]] == [
        "report_run_001_001",
        "report_run_001_002",
    ]
    assert payload["report_history"][0]["status"] == "superseded"
    assert payload["prior_review_feedback"][0]["message"] == "Pricing section was missing."


def test_reviewer_rejects_when_prior_feedback_still_unresolved() -> None:
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    save_source(store, "source_001", entity="Acme", metadata={"dimension": "official"})
    save_claim(store, "claim_001", source_ids=["source_001"])
    save_report(store, claim_ids=["claim_001"], source_ids=["source_001"])
    journal.append(
        RoundEvent(
            id="run_001:reviewer:1",
            run_id="run_001",
            agent="reviewer",
            round=1,
            decision="rework",
            review_feedback=[
                ReviewFeedback(
                    issue="missing_source",
                    target_agent="collector",
                    target_artifact_id="collector_coverage",
                    message="Market share evidence is missing.",
                    required_action="Collect market share evidence.",
                    question="market share",
                )
            ],
        )
    )

    result = ReviewerAgent(store, journal=journal).run_round(
        make_question_context("market share"),
        AgentState(agent="reviewer"),
    )

    assert result.completed is False
    assert result.review_feedback[0].target_agent == "collector"
    assert "still unresolved" in result.review_feedback[0].message


def test_reviewer_rejects_competitive_report_with_too_few_sources() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001", entity="Acme")
    save_source(store, "source_002", entity="Beta")
    save_claim(store, source_ids=["source_001"])
    save_report(store, source_ids=["source_001"])

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is False
    assert result.signals == ["rework_required"]
    assert any(
        item.issue == "missing_source" and item.target_agent == "collector"
        for item in result.review_feedback
    )


def test_reviewer_rejects_missing_competitor_source() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001", entity="Acme")
    save_source(store, "source_002", entity="Acme")
    save_source(store, "source_003", entity="Acme")
    save_claim(store, source_ids=["source_001"])
    save_report(store, source_ids=["source_001"])

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is False
    feedback = result.review_feedback[0]
    assert feedback.issue == "missing_source"
    assert feedback.target_agent == "collector"
    assert "Beta" in feedback.message


def test_reviewer_does_not_count_synthetic_rework_source_as_competitor_coverage() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001", entity="Acme")
    save_source(store, "source_002", entity="Acme")
    store.save_source(
        SourceArtifact(
            id="collector_coverage_v1",
            run_id="run_001",
            url="https://rework.local/collector_coverage",
            title="Rework source for collector_coverage",
            snippet="Collect more sources for Beta.",
        )
    )
    save_claim(store, source_ids=["source_001"])
    save_report(store, source_ids=["source_001"])

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is False
    assert any(
        item.issue == "missing_source"
        and item.target_agent == "collector"
        and "Beta" in item.message
        for item in result.review_feedback
    )


def test_reviewer_rejects_competitor_source_without_competitor_claim() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001", entity="Acme")
    save_source(store, "source_002", entity="Beta")
    save_source(store, "source_003", entity="Acme")
    save_claim(store, source_ids=["source_001"])
    save_report(store, source_ids=["source_001"])

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is False
    assert any(
        item.issue == "unsupported_claim"
        and item.target_agent == "analyst"
        and "Beta" in item.message
        for item in result.review_feedback
    )


def test_reviewer_rejects_report_that_does_not_answer_user_question() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001", entity="Acme")
    save_source(store, "source_002", entity="Beta")
    save_source(store, "source_003", entity="Acme")
    save_claim(store, "claim_001", source_ids=["source_001"])
    save_claim(store, "claim_002", source_ids=["source_002"])
    save_report(
        store,
        claim_ids=["claim_001", "claim_002"],
        source_ids=["source_001", "source_002"],
        sections={
            "Overview": "Acme and Beta are compared at a high level.",
            "Feature comparison": "The products differ in workflow.",
            "Pricing": "Pricing is not available.",
            "SWOT": "Strengths and weaknesses are listed.",
            "Sources": "- source_001\n- source_002",
        },
    )

    result = ReviewerAgent(store).run_round(
        make_question_context("受众定位，市场份额，产品能力"),
        AgentState(agent="reviewer"),
    )

    assert result.completed is False
    question_feedback = [
        item
        for item in result.review_feedback
        if item.issue == "missing_source"
        and item.target_agent == "collector"
        and "受众定位" in item.message
    ]
    assert question_feedback
    assert question_feedback[0].question == "受众定位，市场份额，产品能力"
    assert question_feedback[0].dimension == "受众定位, 市场份额, 产品能力"


def test_reviewer_rejects_missing_sections_with_writer_feedback() -> None:
    store = InMemoryArtifactStore()
    save_source(store)
    save_claim(store)
    save_report(
        store,
        sections={
            "Overview": "Summary.",
            "Feature comparison": "Comparison.",
            "SWOT": "SWOT.",
            "Sources": "- source_001",
        },
    )

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is False
    assert result.signals == ["rework_required"]
    assert result.review_feedback[0].issue == "missing_section"
    assert result.review_feedback[0].target_agent == "writer"
    assert result.review_feedback[0].target_artifact_id == "report_run_001_001"


def test_reviewer_rejects_unknown_report_claim_with_analyst_feedback() -> None:
    store = InMemoryArtifactStore()
    save_source(store)
    save_report(store, claim_ids=["claim_missing"])

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is False
    assert result.review_feedback[0].issue == "unsupported_claim"
    assert result.review_feedback[0].target_agent == "analyst"
    assert result.review_feedback[0].target_artifact_id == "claim_missing"


def test_reviewer_routes_missing_source_to_collector() -> None:
    store = InMemoryArtifactStore()
    save_claim(store, source_ids=["source_missing"])
    save_report(store, source_ids=["source_missing"])

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is False
    assert result.review_feedback[0].issue == "missing_source"
    assert result.review_feedback[0].target_agent == "collector"
    assert result.review_feedback[0].target_artifact_id == "source_missing"


def test_reviewer_rejects_report_source_ids_not_covered_by_claims() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001")
    save_source(store, "source_002")
    save_claim(store, source_ids=["source_001"])
    save_report(store, source_ids=["source_001", "source_002"])

    result = ReviewerAgent(store).run_round(make_context(), AgentState(agent="reviewer"))

    assert result.completed is False
    assert result.review_feedback[0].issue == "unsupported_claim"
    assert result.review_feedback[0].target_agent == "analyst"
    assert result.review_feedback[0].target_artifact_id == "report_run_001_001"


def test_reviewer_can_run_through_harness_without_tools() -> None:
    store = InMemoryArtifactStore()
    save_source(store, "source_001", entity="Acme")
    save_source(store, "source_002", entity="Beta")
    save_source(store, "source_003", entity="Acme")
    save_claim(store, "claim_001", source_ids=["source_001"])
    save_claim(store, "claim_002", source_ids=["source_002"])
    save_report(
        store,
        claim_ids=["claim_001", "claim_002"],
        source_ids=["source_001", "source_002"],
    )
    context = make_context()
    harness = RuntimeHarness(
        InMemoryJournalStore(),
        ToolRuntime(),
        InMemoryCheckpointStore(),
    )

    result = harness.run_agent(context, ReviewerAgent(store))

    assert result.agent == "reviewer"
    assert result.decision == "stop"
    assert result.output_artifact_ids == ["report_run_001_001"]


# ── Claim cross-check (Module 35) ──────────────────────────────


class _ScriptedReviewerRuntime:
    """Routes review-task and verify-task prompts to distinct payloads."""

    def __init__(self, review_payload: dict, verify_payload: dict) -> None:
        self._review = review_payload
        self._verify = verify_payload
        self.requests: list = []

    def complete(self, request):
        self.requests.append(request)
        last_user = request.messages[-1]["content"] if request.messages else ""
        # Verification prompt is uniquely identifiable by this token
        # in the task description.
        if "Cross-check each claim" in last_user:
            return ModelResponse(ok=True, parsed=self._verify)
        return ModelResponse(ok=True, parsed=self._review)


def _build_full_report_store(tmp_path) -> tuple[InMemoryArtifactStore, str]:
    """Two-competitor fully-sourced fixture with on-disk content_refs."""
    store = InMemoryArtifactStore()
    acme_path = tmp_path / "source_001.txt"
    acme_path.write_text(
        "Acme markets a team plan starting at $10/seat. Source attribution.",
        encoding="utf-8",
    )
    beta_path = tmp_path / "source_002.txt"
    beta_path.write_text(
        "Beta has a published team plan with collaboration features.",
        encoding="utf-8",
    )
    acme2_path = tmp_path / "source_003.txt"
    acme2_path.write_text(
        "Acme additional analyst coverage and overview.",
        encoding="utf-8",
    )
    save_source(
        store,
        "source_001",
        entity="Acme",
        metadata={"content_ref": f"file:{acme_path}"},
    )
    save_source(
        store,
        "source_002",
        entity="Beta",
        metadata={"content_ref": f"file:{beta_path}"},
    )
    save_source(
        store,
        "source_003",
        entity="Acme",
        metadata={"content_ref": f"file:{acme2_path}"},
    )
    save_claim(store, "claim_001", source_ids=["source_001"])
    save_claim(store, "claim_002", source_ids=["source_002"])
    save_claim(store, "claim_003", source_ids=["source_003"])
    save_report(
        store,
        claim_ids=["claim_001", "claim_002", "claim_003"],
        source_ids=["source_001", "source_002", "source_003"],
        sections={
            "Overview": "Summary covering Acme and Beta competitors.",
            "Feature comparison": "Comparison.",
            "Pricing": "Pricing.",
            "SWOT": "SWOT.",
            "Sources": "- source_001\n- source_002\n- source_003",
        },
    )
    return store, "report_run_001_001"


def test_reviewer_cross_check_marks_unsupported_claim_advisory(tmp_path) -> None:
    store, _ = _build_full_report_store(tmp_path)
    runtime = _ScriptedReviewerRuntime(
        review_payload={"feedback": []},
        verify_payload={
            "verdicts": [
                {"claim_id": "claim_001", "accuracy": "supported", "evidence": "ok"},
                {
                    "claim_id": "claim_002",
                    "accuracy": "unsupported",
                    "evidence": "Source mentions a free plan, not a team plan.",
                },
            ]
        },
    )
    agent = ReviewerAgent(store, model_runtime=runtime)
    result = agent.run_round(make_context(), AgentState(agent="reviewer", round=1))

    # Reviewer still finishes (no blocking feedback) but ships the
    # advisory in review_feedback so the orchestrator's
    # approved_with_caveats branch can promote it to caveats.
    assert result.completed is True
    advisories = [fb for fb in result.review_feedback if not fb.blocking]
    assert len(advisories) == 1
    assert advisories[0].issue == "unsupported_claim"
    assert advisories[0].target_artifact_id == "claim_002"
    assert advisories[0].severity == "advisory"
    # Claim was rewritten to v2 with accuracy=unsupported, lineage chain intact.
    claim_v2 = store.get_artifact("claim_002_v2_verified")
    assert claim_v2.accuracy == "unsupported"
    assert claim_v2.supersedes_id == "claim_002"


def test_reviewer_cross_check_does_not_bump_supported_claim(tmp_path) -> None:
    """A 'supported' verdict must NOT version-bump the claim — that
    would flood the artifact store with v2 noise on every reviewer
    round when nothing actually changed."""
    store, _ = _build_full_report_store(tmp_path)
    runtime = _ScriptedReviewerRuntime(
        review_payload={"feedback": []},
        verify_payload={
            "verdicts": [
                {"claim_id": "claim_001", "accuracy": "supported", "evidence": "ok"},
                {"claim_id": "claim_002", "accuracy": "supported", "evidence": "ok"},
            ]
        },
    )
    agent = ReviewerAgent(store, model_runtime=runtime)
    result = agent.run_round(make_context(), AgentState(agent="reviewer", round=1))

    assert result.completed is True
    assert result.review_feedback == []
    # Original claims still v1 and unchanged.
    assert store.get_artifact("claim_001").version == 1
    assert store.get_artifact("claim_002").version == 1


def test_reviewer_skips_cross_check_without_model_runtime(tmp_path) -> None:
    """Without a model_runtime the verification step is silently
    skipped so deterministic / fake-pipeline runs are unaffected."""
    store, _ = _build_full_report_store(tmp_path)
    agent = ReviewerAgent(store, model_runtime=None)

    result = agent.run_round(make_context(), AgentState(agent="reviewer", round=1))

    assert result.completed is True
    # Claims untouched.
    assert store.get_artifact("claim_001").accuracy == "unverified"
    assert store.get_artifact("claim_002").accuracy == "unverified"


def test_reviewer_skips_cross_check_when_source_content_missing() -> None:
    """If sources have no content_ref on disk, skip verification —
    judging the claim against just title+snippet would hallucinate."""
    store = InMemoryArtifactStore()
    save_source(store, "source_001", entity="Acme")  # no content_ref
    save_source(store, "source_002", entity="Beta")
    save_source(store, "source_003", entity="Acme")
    save_claim(store, "claim_001", source_ids=["source_001"])
    save_claim(store, "claim_002", source_ids=["source_002"])
    save_claim(store, "claim_003", source_ids=["source_003"])
    save_report(
        store,
        claim_ids=["claim_001", "claim_002", "claim_003"],
        source_ids=["source_001", "source_002", "source_003"],
        sections={
            "Overview": "Summary covering Acme and Beta competitors.",
            "Feature comparison": "Comparison.",
            "Pricing": "Pricing.",
            "SWOT": "SWOT.",
            "Sources": "- source_001\n- source_002\n- source_003",
        },
    )
    runtime = _ScriptedReviewerRuntime(
        review_payload={"feedback": []},
        # If this verdict ever reached the agent, claim_001 would be
        # downgraded — but content_ref is missing so verification must
        # short-circuit before touching the model.
        verify_payload={
            "verdicts": [
                {"claim_id": "claim_001", "accuracy": "unsupported", "evidence": "x"},
            ]
        },
    )
    agent = ReviewerAgent(store, model_runtime=runtime)
    result = agent.run_round(make_context(), AgentState(agent="reviewer", round=1))

    assert result.completed is True
    assert result.review_feedback == []
    assert store.get_artifact("claim_001").accuracy == "unverified"
    # No verification call — the only model request would be the
    # primary review (which we kept as feedback=[] so the run passes).
    assert len(runtime.requests) <= 1
