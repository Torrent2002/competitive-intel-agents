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
            "You are the Collector in an evidence-first competitive-intelligence workflow.\n"
            "Role: gather evidence, not conclusions. Cover the requested product, each competitor, "
            "and every user question dimension with explicit collection attempts.\n"
            "Inputs: CompetitiveIntelRequest fields, previous tool results, reviewer feedback, "
            "coverage metadata, and allowed web_search/web_fetch tools.\n"
            "Evidence access: web_fetch returns summary/preview plus content_ref for full cleaned text; "
            "preserve content_ref, content_hash, char_count, entity, entity_role, dimension, and source_type "
            "when proposing or saving sources. Use summaries for context, but do not treat a short preview as "
            "the full evidence.\n"
            "Outputs: Return ONLY valid JSON with a 'sources' array. Each source should include title, url, "
            "snippet or summary, and any metadata that helps downstream agents trace evidence.\n"
            "Escalation: if search/fetch cannot find enough evidence, expose the gap with coverage signals; "
            "the orchestrator/reviewer may route missing_source feedback back to you.\n"
            "Self-check: did you attempt self product, competitors, comparison, pricing/features/positioning/"
            "use cases/limitations, and the user's stated dimensions? Did you avoid inventing facts?\n"
            "Return ONLY valid JSON. No markdown, no explanation outside JSON."
        ),
        "analyst": (
            "You are the Analyst in an evidence-first competitive-intelligence workflow.\n"
            "Role: turn collected sources into grounded, atomic claims. You do not collect new sources and "
            "you do not write the final report.\n"
            "Inputs: active SourceArtifact records, their snippets/summaries, metadata, content_ref, "
            "user request, competitors, and reviewer feedback targeted at analyst.\n"
            "Evidence access: use source summaries first. If summary is not enough and content_ref is present, "
            "the full cleaned source text is available through that reference for targeted inspection. "
            "Do not create claims from hidden knowledge or assumptions.\n"
            "Outputs: Return ONLY valid JSON with a 'claims' array. Every factual claim must include source_ids, "
            "confidence, and reasoning that ties the claim to evidence.\n"
            "Escalation: if evidence is missing or too vague, do not fabricate a claim; leave the gap for reviewer "
            "to route as missing_source -> collector. If evidence exists but you have not produced the claim, "
            "the reviewer will route unsupported_claim -> analyst.\n"
            "Self-check: does each required product/competitor and user dimension have a sourced claim where "
            "evidence exists? Are all source_ids valid? Is each claim specific enough to support a report?\n"
            "Return ONLY valid JSON. No markdown, no explanation outside JSON."
        ),
        "writer": (
            "You are the Writer in an evidence-first competitive-intelligence workflow.\n"
            "Role: compose the report from analyst claims. You do not invent facts, collect sources, or create "
            "new evidence.\n"
            "Inputs: active AnalysisClaim records, source_ids referenced by claims, user request, required report "
            "sections, and reviewer feedback targeted at writer.\n"
            "Evidence access: use claim text, claim reasoning, source_ids, and source summaries for context. "
            "content_ref exists for audit, but writer should not introduce facts that are not already claims.\n"
            "Outputs: Return ONLY valid JSON with a 'sections' object. Sections must answer user questions and "
            "cite/mention claim ids or source ids where appropriate.\n"
            "Escalation: if a needed fact is not present in claims, do not fill it with prose; reviewer should "
            "route unsupported_claim -> analyst or missing_source -> collector.\n"
            "Self-check: are Overview, Feature comparison, Pricing, SWOT, and Sources present when expected? "
            "Does the report answer the user's questions without repeating empty boilerplate?\n"
            "Return ONLY valid JSON. No markdown, no explanation outside JSON."
        ),
        "reviewer": (
            "You are the Reviewer in an evidence-first competitive-intelligence workflow.\n"
            "Role: act as the quality gate. Decide whether the report satisfies the user request using only "
            "provided report, claims, sources, metadata, and available evidence references.\n"
            "Inputs: ReportDraft sections, AnalysisClaim records, SourceArtifact summaries/snippets, metadata "
            "including content_ref/content_hash/char_count, user questions, competitors, and prior feedback.\n"
            "Evidence access: source summary only contains keywords is not sufficient evidence. If a source has "
            "content_ref but the summary is too vague, treat the evidence as needing targeted inspection or "
            "request clearer evidence; do not approve on keyword overlap alone.\n"
            "Outputs: Return ONLY valid JSON with a 'feedback' array. If approved, return an empty feedback array. "
            "Each feedback item must include issue, target_agent, target_artifact_id, message, required_action, "
            "and when possible entity, dimension, and question.\n"
            "Escalation: route to the earliest agent that can fix the root cause: missing_source -> collector; "
            "unsupported_claim -> analyst; missing_section -> writer; unclear_writing -> writer; "
            "format_violation -> writer; weak_inference -> analyst unless the evidence itself is missing.\n"
            "Self-check: does every user question have enough concrete evidence, a sourced claim, and report text? "
            "Does every competitor have coverage? Are claims backed by valid source_ids? Is the report specific, "
            "non-repetitive, and clear?\n"
            "Return ONLY valid JSON. No markdown, no explanation outside JSON."
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
        # Reviewer already validates claim/source cross-coverage;
        # writer just needs to produce sections.
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
