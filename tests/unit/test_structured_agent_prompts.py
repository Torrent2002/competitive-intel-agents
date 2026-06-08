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

    try:
        validator.validate(
            "writer",
            {
                "sections": {"Overview": "Summary"},
                "claim_ids": ["claim_001"],
                "source_ids": ["source_missing"],
                "claims": [{"id": "claim_001", "source_ids": ["source_001"]}],
            },
        )
    except ValidationError as exc:
        assert "source_missing" in str(exc)
    else:
        raise AssertionError("expected validation failure")


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
