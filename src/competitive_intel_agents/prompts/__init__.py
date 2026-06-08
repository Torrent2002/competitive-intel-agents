"""Structured prompt builders and output validators for agents."""

from __future__ import annotations

import json
from typing import Any

from competitive_intel_agents.models import (
    AgentName,
    ModelRequest,
    VALID_AGENTS,
    VALID_REVIEW_ISSUES,
)


class ValidationError(ValueError):
    """Raised when structured model output violates an agent contract."""


class AgentPromptLibrary:
    """Build role-specific structured JSON model requests."""

    SYSTEM_PROMPTS: dict[AgentName, str] = {
        "collector": (
            "You are the Collector in an evidence-first workflow. "
            "Return only structured JSON tool plans or source summaries."
        ),
        "analyst": (
            "You are the Analyst in an evidence-first workflow. "
            "Every factual claim must include source_ids."
        ),
        "writer": (
            "You are the Writer in an evidence-first workflow. "
            "Draft only from provided claims and source ids."
        ),
        "reviewer": (
            "You are the Reviewer in an evidence-first workflow. "
            "Return routable feedback with issue, target_agent, and target_artifact_id."
        ),
    }

    def build(
        self,
        agent: AgentName,
        task: str,
        context: dict[str, Any],
    ) -> ModelRequest:
        if agent not in VALID_AGENTS:
            raise ValueError(f"invalid agent: {agent}")
        return ModelRequest(
            agent=agent,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPTS[agent]},
                {
                    "role": "user",
                    "content": (
                        f"{task}\n\nContext JSON:\n"
                        f"{json.dumps(context, sort_keys=True)}"
                    ),
                },
            ],
            response_format="json",
            temperature=0.0,
        )


class StructuredOutputValidator:
    """Validate provider-backed structured outputs before artifact creation."""

    def validate(self, agent: AgentName, payload: dict[str, Any]) -> dict[str, Any]:
        if agent == "collector":
            return self._validate_collector(payload)
        if agent == "analyst":
            return self._validate_analyst(payload)
        if agent == "writer":
            return self._validate_writer(payload)
        if agent == "reviewer":
            return self._validate_reviewer(payload)
        raise ValidationError(f"unsupported agent: {agent}")

    @staticmethod
    def _validate_collector(payload: dict[str, Any]) -> dict[str, Any]:
        sources = payload.get("sources", [])
        if sources is not None and not isinstance(sources, list):
            raise ValidationError("collector sources must be a list")
        return payload

    @staticmethod
    def _validate_analyst(payload: dict[str, Any]) -> dict[str, Any]:
        claims = payload.get("claims", [])
        if not isinstance(claims, list):
            raise ValidationError("claims must be a list")
        for claim in claims:
            if not claim.get("source_ids"):
                raise ValidationError("analyst claim source_ids are required")
        return payload

    @staticmethod
    def _validate_writer(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload.get("sections", {}), dict):
            raise ValidationError("writer sections must be an object")
        report_source_ids = set(payload.get("source_ids", []))
        claim_source_ids: set[str] = set()
        for claim in payload.get("claims", []):
            claim_source_ids.update(claim.get("source_ids", []))
        missing = sorted(report_source_ids - claim_source_ids)
        if missing:
            raise ValidationError(
                f"writer source_ids not covered by claims: {', '.join(missing)}"
            )
        return payload

    @staticmethod
    def _validate_reviewer(payload: dict[str, Any]) -> dict[str, Any]:
        feedback_items = payload.get("feedback", [])
        if not isinstance(feedback_items, list):
            raise ValidationError("reviewer feedback must be a list")
        for item in feedback_items:
            if item.get("issue") not in VALID_REVIEW_ISSUES:
                raise ValidationError("reviewer feedback issue is invalid")
            if item.get("target_agent") not in VALID_AGENTS:
                raise ValidationError("reviewer feedback target_agent is invalid")
            for field_name in ("target_artifact_id", "message", "required_action"):
                if not item.get(field_name):
                    raise ValidationError(f"reviewer feedback {field_name} is required")
        return payload


__all__ = [
    "AgentPromptLibrary",
    "StructuredOutputValidator",
    "ValidationError",
]
