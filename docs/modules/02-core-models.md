# 02 Core Models

## Goal

Define the shared data contracts used by every module.

## Scope

In scope:

- Run identity.
- Agent identity.
- Agent profiles.
- Requests and run results.
- Round events.
- Tool calls.
- Tool results.
- Model requests and responses.
- Agent state and round results.
- Checkpoints.
- Harness decisions.
- Source artifacts.
- Analysis claims.
- Report drafts.
- Review feedback.

Out of scope:

- Persistence.
- Model provider integration.
- Business logic.

## Core Types

```python
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
```

Required shared models:

- `CompetitiveIntelRequest`
- `AgentProfile`
- `RunContext`
- `ToolCall`
- `ToolResult`
- `ModelRequest`
- `ModelResponse`
- `AgentState`
- `AgentRoundResult`
- `AgentResult`
- `RoundEvent`
- `Checkpoint`
- `SourceArtifact`
- `AnalysisClaim`
- `ReportDraft`
- `ReviewFeedback`
- `RunResult`

## Minimal Fields

### CompetitiveIntelRequest

- `company`: target company or product.
- `market`: optional market/category.
- `competitors`: optional competitor list.
- `questions`: optional user-provided focus areas.

### RunContext

- `run_id`
- `request`
- `agent_profiles`
- `started_at`
- `metadata`

### AgentProfile

- `agent`
- `max_rounds`
- `allowed_tools`
- `model`
- `strategy`

### ToolCall

- `id`
- `name`
- `args`
- `requested_by`
- `signature`

### ToolResult

- `tool_call_id`
- `ok`
- `data`
- `error`
- `preview`

### ModelRequest

- `agent`
- `messages`
- `response_format`
- `temperature`
- `metadata`

### ModelResponse

- `ok`
- `content`
- `parsed`
- `usage`
- `error`

### AgentState

- `agent`
- `round`
- `memory`
- `last_checkpoint_id`

### AgentRoundResult

- `completed`
- `tool_calls`
- `output_artifact_ids`
- `signals`
- `message`
- `error`

### AgentResult

- `agent`
- `decision`
- `rounds`
- `output_artifact_ids`
- `error`

### RoundEvent

- `id`
- `run_id`
- `agent`
- `round`
- `tool_calls`
- `output_artifact_ids`
- `signals`
- `decision`
- `timestamp`

### Checkpoint

- `id`
- `run_id`
- `agent`
- `round`
- `state`
- `created_at`

### SourceArtifact

- `id`
- `run_id`
- `url`
- `title`
- `snippet`
- `retrieved_at`
- `source_type`
- `status`
- `version`
- `supersedes_id`

### AnalysisClaim

- `id`
- `run_id`
- `text`
- `source_ids`
- `confidence`
- `reasoning`
- `status`
- `version`
- `supersedes_id`

### ReportDraft

- `id`
- `run_id`
- `sections`
- `claim_ids`
- `source_ids`
- `status`
- `version`
- `supersedes_id`

### ReviewFeedback

- `issue`
- `target_agent`
- `target_artifact_id`
- `message`
- `required_action`

### RunResult

- `run_id`
- `status`
- `report_id`
- `review_feedback`
- `error`

## Contract Notes

- Every persisted object should have a stable `id`.
- Every round event should include `run_id`, `agent`, `round`, `decision`, and `timestamp`.
- Claims should carry `source_ids`.
- Review feedback should carry `issue`, `target_agent`, `target_artifact_id`, and `required_action`.
- Reworked artifacts should not overwrite old artifacts in place. Use `status`, `version`, and `supersedes_id`.
- Phase 1 provenance means factual claims carry source ids. Full causal-chain replay can be implemented later.

## Tests

- Validate required fields.
- Validate invalid decisions are rejected.
- Validate invalid review issues are rejected.
- Validate a claim can reference source ids.
- Validate artifact status and version fields.
- Validate agent profile budget and allowed tool fields.
- Validate JSON serialization and deserialization.

## Done Criteria

- Models are importable from one stable module.
- Tests cover valid and invalid examples.
- No storage or runtime behavior is mixed into the models.
