# 13 Rework Loop

## Goal

Route reviewer feedback to the responsible agent and rerun only the needed part of the pipeline.

## Scope

In scope:

- Parse `ReviewFeedback`.
- Map feedback issue to target agent.
- Limit rework attempts.
- Re-run downstream agents after a fix.

Out of scope:

- Complex planning.
- Human-in-the-loop editing.
- Parallel rework.

## Routing v0

| Target Agent | Re-run Sequence |
|---|---|
| Collector | Collector -> Analyst -> Writer -> Reviewer |
| Analyst | Analyst -> Writer -> Reviewer |
| Writer | Writer -> Reviewer |

## Tests

- Routes `missing_source` to Collector.
- Routes `unsupported_claim` to Analyst.
- Routes `format_violation` to Writer.
- Stops after max rework attempts.

## Done Criteria

- Reviewer rejection can lead to a bounded automatic rework.
- Infinite rework loops are impossible.

