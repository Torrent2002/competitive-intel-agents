# 12 Reviewer Agent

## Goal

Check report quality and return structured approval or rework feedback.

## Scope

In scope:

- Check required sections.
- Check factual claims have source ids.
- Check source ids exist.
- Return structured `ReviewFeedback`.

Out of scope:

- Deep semantic truth verification.
- External fact checking.
- Golden regression.

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
- Rejects claims without source ids.
- Rejects unknown source ids.
- Returns target agent and artifact id.
- Routes `missing_section` to Writer.

## Done Criteria

- Orchestrator can decide approve vs rework from reviewer output.
- Every rejection is machine-routable.
