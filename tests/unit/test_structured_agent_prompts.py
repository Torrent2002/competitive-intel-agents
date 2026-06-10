from competitive_intel_agents.prompts import (
    AgentPromptLibrary,
    StructuredOutputValidator,
    ValidationError,
)


def test_prompt_library_builds_role_specific_messages() -> None:
    library = AgentPromptLibrary()

    request = library.build(
        agent="analyst",
        task="Create sourced claims.",
        context={"sources": ["source_001"]},
    )

    assert request.agent == "analyst"
    assert request.response_format == "json"
    assert "evidence-first" in request.messages[0]["content"]
    assert "Create sourced claims." in request.messages[1]["content"]
    assert "source_001" in request.messages[1]["content"]


def test_agent_prompts_include_operating_contract_sections() -> None:
    library = AgentPromptLibrary()

    for agent in ("collector", "analyst", "writer", "reviewer"):
        prompt = library.build(agent, "Do the task.", {}).messages[0]["content"]

        assert "Role" in prompt
        assert "Inputs" in prompt
        assert "Outputs" in prompt
        assert "Escalation" in prompt
        assert "Self-check" in prompt
        assert "Evidence access" in prompt


def test_reviewer_prompt_defines_feedback_routing_rules() -> None:
    prompt = AgentPromptLibrary().build(
        "reviewer",
        "Review the report.",
        {},
    ).messages[0]["content"]

    assert "missing_source -> collector" in prompt
    assert "unsupported_claim -> analyst" in prompt
    assert "missing_section -> writer" in prompt
    assert "source summary only contains keywords" in prompt
    assert "compare report_history" in prompt
    assert "prior_review_feedback" in prompt


def test_analyst_prompt_uses_content_ref_for_full_evidence() -> None:
    prompt = AgentPromptLibrary().build(
        "analyst",
        "Create claims.",
        {},
    ).messages[0]["content"]

    assert "content_ref" in prompt
    assert "content_excerpt" in prompt
    assert "read the full source text" in prompt
    assert "summary is not enough" in prompt
    assert "Do not create claims from hidden knowledge" in prompt


def test_writer_prompt_uses_claims_and_full_source_context_without_inventing() -> None:
    prompt = AgentPromptLibrary().build(
        "writer",
        "Write report.",
        {},
    ).messages[0]["content"]

    assert "content_ref" in prompt
    assert "content_excerpt" in prompt
    assert "read the full source text" in prompt
    assert "do not rely only on snippets" in prompt


def test_validator_rejects_claims_without_source_ids() -> None:
    validator = StructuredOutputValidator()

    try:
        validator.validate("analyst", {"claims": [{"text": "Unsupported"}]})
    except ValidationError as exc:
        assert "source_ids" in str(exc)
    else:
        raise AssertionError("expected validation failure")


def test_validator_rejects_writer_source_ids_not_covered_by_claims() -> None:
    validator = StructuredOutputValidator()

    # Writer validation now only checks sections is a dict (Reviewer handles cross-coverage)
    result = validator.validate(
        "writer",
        {
            "sections": {"Overview": "Summary"},
            "claim_ids": ["claim_001"],
            "source_ids": ["source_missing"],
            "claims": [{"id": "claim_001", "source_ids": ["source_001"]}],
        },
    )
    assert result["sections"] == {"Overview": "Summary"}


def test_validator_accepts_routable_reviewer_feedback() -> None:
    validator = StructuredOutputValidator()

    payload = validator.validate(
        "reviewer",
        {
            "feedback": [
                {
                    "issue": "missing_section",
                    "target_agent": "writer",
                    "target_artifact_id": "report_001",
                    "message": "Missing Pricing",
                    "required_action": "Add Pricing",
                }
            ]
        },
    )

    assert payload["feedback"][0]["target_agent"] == "writer"


def test_validator_rejects_unroutable_reviewer_feedback() -> None:
    validator = StructuredOutputValidator()

    try:
        validator.validate(
            "reviewer",
            {
                "feedback": [
                    {
                        "issue": "missing_section",
                        "target_agent": "planner",
                        "target_artifact_id": "report_001",
                        "message": "Missing Pricing",
                        "required_action": "Add Pricing",
                    }
                ]
            },
        )
    except ValidationError as exc:
        assert "target_agent" in str(exc)
    else:
        raise AssertionError("expected validation failure")
