"""Shared data contracts for the competitive intelligence pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar, Literal, TypeVar


AgentName = Literal["collector", "analyst", "writer", "reviewer"]
HarnessDecision = Literal["continue", "stop", "retry", "rework", "abort"]
ArtifactStatus = Literal["active", "superseded", "rejected"]
ReviewIssue = Literal[
    "missing_source",
    "unsupported_claim",
    "weak_inference",
    "unclear_writing",
    "format_violation",
    "missing_section",
]

VALID_AGENTS = {"collector", "analyst", "writer", "reviewer"}
VALID_DECISIONS = {"continue", "stop", "retry", "rework", "abort"}
VALID_ARTIFACT_STATUSES = {"active", "superseded", "rejected"}
VALID_REVIEW_ISSUES = {
    "missing_source",
    "unsupported_claim",
    "weak_inference",
    "unclear_writing",
    "format_violation",
    "missing_section",
}
VALID_CLAIM_ACCURACY = {
    # Claim has not been cross-checked against its source content yet.
    # All freshly-saved claims start in this state and stay here when
    # the reviewer can't run (no model_runtime, source content_ref
    # missing, etc.).
    "unverified",
    # The source text directly supports the claim.
    "supported",
    # Source text partially supports the claim — quoted but with caveats
    # or missing context. Surfaced to readers as a soft warning.
    "partial",
    # Source text contradicts or fails to back the claim. Triggers a
    # non-blocking advisory feedback so the report ships through
    # ``approved_with_caveats`` rather than failing.
    "unsupported",
}

T = TypeVar("T", bound="SerializableModel")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def require_non_empty(value: str, field_name: str) -> None:
    if not value:
        raise ValueError(f"{field_name} is required")


def require_choice(value: str, valid_values: set[str], field_name: str) -> None:
    if value not in valid_values:
        raise ValueError(f"invalid {field_name}: {value}")


class SerializableModel:
    """Small serialization helper for dataclass contracts."""

    _nested_list_types: ClassVar[dict[str, type[SerializableModel]]] = {}
    _nested_types: ClassVar[dict[str, type[SerializableModel]]] = {}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls: type[T], payload: dict[str, Any]) -> T:
        data = dict(payload)
        for field_name, nested_type in cls._nested_types.items():
            if isinstance(data.get(field_name), dict):
                data[field_name] = nested_type.from_dict(data[field_name])
        for field_name, nested_type in cls._nested_list_types.items():
            if isinstance(data.get(field_name), list):
                data[field_name] = [
                    nested_type.from_dict(item) if isinstance(item, dict) else item
                    for item in data[field_name]
                ]
        return cls(**data)


@dataclass(frozen=True)
class CompetitiveIntelRequest(SerializableModel):
    company: str
    market: str | None = None
    competitors: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        require_non_empty(self.company, "company")


@dataclass(frozen=True)
class AgentProfile(SerializableModel):
    agent: AgentName
    max_rounds: int
    allowed_tools: list[str] = field(default_factory=list)
    model: str = "fake"
    strategy: str = ""

    def __post_init__(self) -> None:
        require_choice(self.agent, VALID_AGENTS, "agent")
        if self.max_rounds < 1:
            raise ValueError("max_rounds must be positive")


@dataclass(frozen=True)
class RunContext(SerializableModel):
    run_id: str
    request: CompetitiveIntelRequest
    agent_profiles: dict[str, AgentProfile]
    started_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    _nested_types: ClassVar[dict[str, type[SerializableModel]]] = {
        "request": CompetitiveIntelRequest
    }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunContext":
        data = dict(payload)
        if isinstance(data.get("request"), dict):
            data["request"] = CompetitiveIntelRequest.from_dict(data["request"])
        if isinstance(data.get("agent_profiles"), dict):
            data["agent_profiles"] = {
                name: AgentProfile.from_dict(profile)
                if isinstance(profile, dict)
                else profile
                for name, profile in data["agent_profiles"].items()
            }
        return cls(**data)

    def __post_init__(self) -> None:
        require_non_empty(self.run_id, "run_id")


@dataclass(frozen=True)
class ToolCall(SerializableModel):
    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    requested_by: AgentName = "collector"
    signature: str = ""

    def __post_init__(self) -> None:
        require_non_empty(self.id, "id")
        require_non_empty(self.name, "name")
        require_choice(self.requested_by, VALID_AGENTS, "requested_by")


@dataclass(frozen=True)
class ToolResult(SerializableModel):
    tool_call_id: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    preview: str = ""

    def __post_init__(self) -> None:
        require_non_empty(self.tool_call_id, "tool_call_id")


@dataclass(frozen=True)
class ModelRequest(SerializableModel):
    agent: AgentName
    messages: list[dict[str, str]]
    response_format: str | None = None
    temperature: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_choice(self.agent, VALID_AGENTS, "agent")


@dataclass(frozen=True)
class ModelResponse(SerializableModel):
    ok: bool
    content: str = ""
    parsed: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class AgentState(SerializableModel):
    agent: AgentName
    round: int = 0
    memory: dict[str, Any] = field(default_factory=dict)
    last_checkpoint_id: str | None = None

    def __post_init__(self) -> None:
        require_choice(self.agent, VALID_AGENTS, "agent")
        if self.round < 0:
            raise ValueError("round must be non-negative")


@dataclass(frozen=True)
class AgentRoundResult(SerializableModel):
    completed: bool = False
    tool_calls: list[ToolCall] = field(default_factory=list)
    output_artifact_ids: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    review_feedback: list["ReviewFeedback"] = field(default_factory=list)
    message: str = ""
    error: str | None = None

    _nested_list_types: ClassVar[dict[str, type[SerializableModel]]] = {
        "tool_calls": ToolCall
    }


@dataclass(frozen=True)
class AgentResult(SerializableModel):
    agent: AgentName
    decision: HarnessDecision
    rounds: int
    output_artifact_ids: list[str] = field(default_factory=list)
    review_feedback: list["ReviewFeedback"] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        require_choice(self.agent, VALID_AGENTS, "agent")
        require_choice(self.decision, VALID_DECISIONS, "decision")
        if self.rounds < 0:
            raise ValueError("rounds must be non-negative")


@dataclass(frozen=True)
class RoundEvent(SerializableModel):
    id: str
    run_id: str
    agent: AgentName
    round: int
    decision: HarnessDecision
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    output_artifact_ids: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    review_feedback: list["ReviewFeedback"] = field(default_factory=list)
    timestamp: str = field(default_factory=utc_now_iso)

    _nested_list_types: ClassVar[dict[str, type[SerializableModel]]] = {
        "tool_calls": ToolCall
    }

    def __post_init__(self) -> None:
        require_non_empty(self.id, "id")
        require_non_empty(self.run_id, "run_id")
        require_choice(self.agent, VALID_AGENTS, "agent")
        require_choice(self.decision, VALID_DECISIONS, "decision")
        if self.round < 0:
            raise ValueError("round must be non-negative")


@dataclass(frozen=True)
class Checkpoint(SerializableModel):
    id: str
    run_id: str
    agent: AgentName
    round: int
    state: dict[str, Any]
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        require_non_empty(self.id, "id")
        require_non_empty(self.run_id, "run_id")
        require_choice(self.agent, VALID_AGENTS, "agent")
        if self.round < 0:
            raise ValueError("round must be non-negative")


@dataclass(frozen=True)
class VersionedArtifact(SerializableModel):
    id: str
    run_id: str
    status: ArtifactStatus = "active"
    version: int = 1
    supersedes_id: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.id, "id")
        require_non_empty(self.run_id, "run_id")
        require_choice(self.status, VALID_ARTIFACT_STATUSES, "status")
        if self.version < 1:
            raise ValueError("version must be positive")


@dataclass(frozen=True)
class SourceArtifact(VersionedArtifact):
    url: str = ""
    title: str = ""
    snippet: str = ""
    retrieved_at: str = field(default_factory=utc_now_iso)
    source_type: str = "web"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        require_non_empty(self.url, "url")


@dataclass(frozen=True)
class AnalysisClaim(VersionedArtifact):
    text: str = ""
    source_ids: list[str] = field(default_factory=list)
    confidence: str = "medium"
    reasoning: str = ""
    # Accuracy of the claim relative to its sources, as judged by the
    # reviewer's ``_verify_claim_support`` cross-check. Defaults to
    # ``unverified`` so analyst output is unaffected; reviewer rewrites
    # this in a v2 of the claim once it has run the LLM check.
    accuracy: str = "unverified"

    def __post_init__(self) -> None:
        super().__post_init__()
        require_non_empty(self.text, "text")
        if not self.source_ids:
            raise ValueError("source_ids must contain at least one source id")
        require_choice(self.accuracy, VALID_CLAIM_ACCURACY, "accuracy")


@dataclass(frozen=True)
class ReportDraft(VersionedArtifact):
    sections: dict[str, str] = field(default_factory=dict)
    claim_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewFeedback(SerializableModel):
    issue: ReviewIssue
    target_agent: AgentName
    target_artifact_id: str
    message: str
    required_action: str
    severity: str = "blocking"
    blocking: bool = True
    entity: str | None = None
    dimension: str | None = None
    question: str | None = None

    def __post_init__(self) -> None:
        require_choice(self.issue, VALID_REVIEW_ISSUES, "issue")
        require_choice(self.target_agent, VALID_AGENTS, "target_agent")
        require_non_empty(self.target_artifact_id, "target_artifact_id")
        require_non_empty(self.message, "message")
        require_non_empty(self.required_action, "required_action")
        require_non_empty(self.severity, "severity")


@dataclass(frozen=True)
class RunResult(SerializableModel):
    run_id: str
    status: str
    report_id: str | None = None
    review_feedback: list[ReviewFeedback] = field(default_factory=list)
    # Caveats are reviewer feedback that survived the bounded rework
    # budget but did NOT block delivery — used by status
    # ``approved_with_caveats`` to surface remaining concerns alongside
    # the final report instead of failing the run.
    caveats: list[ReviewFeedback] = field(default_factory=list)
    error: str | None = None

    _nested_list_types: ClassVar[dict[str, type[SerializableModel]]] = {
        "review_feedback": ReviewFeedback,
        "caveats": ReviewFeedback,
    }

    def __post_init__(self) -> None:
        require_non_empty(self.run_id, "run_id")
        require_non_empty(self.status, "status")


AgentRoundResult._nested_list_types = {
    "tool_calls": ToolCall,
    "review_feedback": ReviewFeedback,
}
AgentResult._nested_list_types = {
    "review_feedback": ReviewFeedback,
}
RoundEvent._nested_list_types = {
    "tool_calls": ToolCall,
    "tool_results": ToolResult,
    "review_feedback": ReviewFeedback,
}
