# 02 Core Models

## Goal

Define the shared data contracts used by every module.

## Scope

In scope:

- Run identity.
- Agent identity.
- Round events.
- Tool calls.
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
```

Suggested models:

- `RunContext`
- `ToolCall`
- `RoundEvent`
- `SourceArtifact`
- `AnalysisClaim`
- `ReportDraft`
- `ReviewFeedback`
- `AgentResult`

## Contract Notes

- Every persisted object should have a stable `id`.
- Every round event should include `run_id`, `agent`, `round`, `decision`, and `timestamp`.
- Claims should carry `source_ids`.
- Review feedback should carry `issue`, `target_agent`, `target_artifact_id`, and `required_action`.

## Tests

- Validate required fields.
- Validate invalid decisions are rejected.
- Validate a claim can reference source ids.
- Validate JSON serialization and deserialization.

## Done Criteria

- Models are importable from one stable module.
- Tests cover valid and invalid examples.
- No storage or runtime behavior is mixed into the models.

