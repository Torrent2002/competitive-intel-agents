import json

import pytest

from competitive_intel_agents.models import (
    AgentProfile,
    AgentResult,
    AgentRoundResult,
    AgentState,
    AnalysisClaim,
    Checkpoint,
    CompetitiveIntelRequest,
    ModelRequest,
    ModelResponse,
    ReviewFeedback,
    ReportDraft,
    RoundEvent,
    RunContext,
    RunResult,
    SourceArtifact,
    ToolCall,
    ToolResult,
)


def test_competitive_intel_request_requires_company() -> None:
    with pytest.raises(ValueError, match="company"):
        CompetitiveIntelRequest(company="")


def test_agent_profile_requires_positive_round_budget() -> None:
    with pytest.raises(ValueError, match="max_rounds"):
        AgentProfile(agent="collector", max_rounds=0)


def test_agent_profile_rejects_invalid_agent_name() -> None:
    with pytest.raises(ValueError, match="agent"):
        AgentProfile(agent="researcher", max_rounds=3)


def test_round_event_rejects_invalid_harness_decision() -> None:
    with pytest.raises(ValueError, match="decision"):
        RoundEvent(
            id="event_001",
            run_id="run_001",
            agent="collector",
            round=1,
            decision="pause",
        )


def test_review_feedback_rejects_invalid_issue() -> None:
    with pytest.raises(ValueError, match="issue"):
        ReviewFeedback(
            issue="bad_logic",
            target_agent="analyst",
            target_artifact_id="claim_001",
            message="Bad reasoning",
            required_action="Try again",
        )


def test_analysis_claim_must_reference_at_least_one_source() -> None:
    with pytest.raises(ValueError, match="source_ids"):
        AnalysisClaim(
            id="claim_001",
            run_id="run_001",
            text="Competitor X leads the market.",
            source_ids=[],
        )


def test_artifact_status_and_version_fields_are_validated() -> None:
    with pytest.raises(ValueError, match="status"):
        SourceArtifact(
            id="source_001",
            run_id="run_001",
            url="https://example.com",
            status="archived",
        )

    with pytest.raises(ValueError, match="version"):
        SourceArtifact(
            id="source_001",
            run_id="run_001",
            url="https://example.com",
            version=0,
        )


def test_model_round_trips_through_json() -> None:
    claim = AnalysisClaim(
        id="claim_001",
        run_id="run_001",
        text="Competitor X has strong collaboration features.",
        source_ids=["source_001"],
        confidence="medium",
        reasoning="The source describes shared docs and team workflows.",
    )

    encoded = json.dumps(claim.to_dict())
    decoded = AnalysisClaim.from_dict(json.loads(encoded))

    assert decoded == claim


def test_all_required_models_are_importable_from_stable_module() -> None:
    assert CompetitiveIntelRequest
    assert AgentProfile
    assert RunContext
    assert ToolCall
    assert ToolResult
    assert ModelRequest
    assert ModelResponse
    assert AgentState
    assert AgentRoundResult
    assert AgentResult
    assert RoundEvent
    assert Checkpoint
    assert SourceArtifact
    assert AnalysisClaim
    assert ReportDraft
    assert ReviewFeedback
    assert RunResult


def test_run_context_round_trips_nested_models() -> None:
    context = RunContext(
        run_id="run_001",
        request=CompetitiveIntelRequest(company="Notion"),
        agent_profiles={
            "collector": AgentProfile(
                agent="collector",
                max_rounds=10,
                allowed_tools=["web_search", "web_fetch"],
            )
        },
    )

    decoded = RunContext.from_dict(json.loads(json.dumps(context.to_dict())))

    assert decoded == context
    assert isinstance(decoded.request, CompetitiveIntelRequest)
    assert isinstance(decoded.agent_profiles["collector"], AgentProfile)


def test_round_event_round_trips_nested_tool_calls() -> None:
    event = RoundEvent(
        id="event_001",
        run_id="run_001",
        agent="collector",
        round=1,
        decision="continue",
        tool_calls=[
            ToolCall(
                id="tool_001",
                name="web_fetch",
                args={"url": "https://example.com"},
                requested_by="collector",
            )
        ],
    )

    decoded = RoundEvent.from_dict(json.loads(json.dumps(event.to_dict())))

    assert decoded == event
    assert isinstance(decoded.tool_calls[0], ToolCall)


def test_agent_round_result_round_trips_review_feedback() -> None:
    result = AgentRoundResult(
        completed=False,
        review_feedback=[
            ReviewFeedback(
                issue="missing_section",
                target_agent="writer",
                target_artifact_id="report_001",
                message="Missing Pricing section.",
                required_action="Add a Pricing section backed by claims.",
            )
        ],
    )

    decoded = AgentRoundResult.from_dict(json.loads(json.dumps(result.to_dict())))

    assert decoded == result
    assert isinstance(decoded.review_feedback[0], ReviewFeedback)


def test_agent_result_and_round_event_round_trip_review_feedback() -> None:
    feedback = ReviewFeedback(
        issue="unsupported_claim",
        target_agent="analyst",
        target_artifact_id="claim_001",
        message="Claim is unsupported.",
        required_action="Revise the claim.",
    )
    agent_result = AgentResult(
        agent="reviewer",
        decision="rework",
        rounds=1,
        review_feedback=[feedback],
    )
    round_event = RoundEvent(
        id="event_001",
        run_id="run_001",
        agent="reviewer",
        round=1,
        decision="rework",
        review_feedback=[feedback],
    )

    decoded_result = AgentResult.from_dict(
        json.loads(json.dumps(agent_result.to_dict()))
    )
    decoded_event = RoundEvent.from_dict(json.loads(json.dumps(round_event.to_dict())))

    assert decoded_result == agent_result
    assert decoded_event == round_event
    assert isinstance(decoded_result.review_feedback[0], ReviewFeedback)
    assert isinstance(decoded_event.review_feedback[0], ReviewFeedback)
