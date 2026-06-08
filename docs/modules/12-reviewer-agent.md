# 12 Reviewer Agent

## Goal

Check report quality and return structured approval or rework feedback.

Reviewer is the quality gate that makes the workflow different from a single
agent writing and grading its own answer.

## Scope

In scope:

- Check required sections.
- Check factual claims have source ids.
- Check source ids exist.
- Return structured `ReviewFeedback` in `AgentRoundResult.review_feedback`.
- Ensure report claim ids point to active `AnalysisClaim` records.
- Ensure report source ids are covered by the referenced claims.
- Route feedback to the earliest responsible stage that can fix the issue.

Out of scope:

- Deep semantic truth verification.
- External fact checking.
- Golden regression.
- Rewriting the report directly.

## Public Interface

```python
ReviewerAgent(artifacts: ArtifactStore)
```

Input:

- `RunContext`
- `AgentState`
- active `ReportDraft`
- active `AnalysisClaim` records
- active `SourceArtifact` records

Output:

- approved report: `AgentRoundResult(completed=True, signals=["approved"])`
- rejected report: `AgentRoundResult(completed=False, signals=["rework_required"], review_feedback=[...])`

Reviewer does not request tools and does not mutate artifacts.

## Review Rules v0

Checks run in deterministic order:

1. Required report sections exist and are non-empty.
2. Every `ReportDraft.claim_id` points to an active `AnalysisClaim`.
3. Every report-level `source_id` points to an active `SourceArtifact`.
4. Every claim-level `source_id` points to an active `SourceArtifact`.
5. Every report-level `source_id` is covered by at least one referenced claim.

The implementation intentionally avoids semantic fact-checking in v0. It checks
the structural evidence chain that later modules can replay:

```text
ReportDraft -> AnalysisClaim -> SourceArtifact
```

## Feedback Contract

Every rejection must include:

- `issue`
- `target_agent`
- `target_artifact_id`
- `message`
- `required_action`

This contract is consumed by the future Rework Loop. Feedback must be
machine-routable; natural-language `message` is explanatory only.

## Feedback Issues v0

| Issue | Target Agent |
|---|---|
| `missing_source` | Collector |
| `unsupported_claim` | Analyst |
| `weak_inference` | Analyst |
| `unclear_writing` | Writer |
| `format_violation` | Writer |
| `missing_section` | Writer |

## Tests

- Approves a fully sourced report.
- Rejects missing sections.
- Rejects unknown report claim ids.
- Rejects unknown source ids from report and claims.
- Rejects report source ids not covered by referenced claims.
- Returns target agent and artifact id.
- Routes `missing_section` to Writer.
- Routes missing evidence to Collector.
- Routes unsupported or weak claims to Analyst.
- Routes unclear prose or format issues to Writer.
- Runs through the runtime harness without tool calls.

## Done Criteria

- Orchestrator can decide approve vs rework from reviewer output.
- Every rejection is machine-routable.
- Reviewer feedback contains `issue`, `target_agent`, `target_artifact_id`, `message`, and `required_action`.
- Reviewer never mutates artifacts directly.
- `AgentRoundResult` can serialize and deserialize nested reviewer feedback.
