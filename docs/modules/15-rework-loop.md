# 15 Rework Loop

## Goal

Route reviewer feedback to the responsible agent and rerun only the needed part of the pipeline.

## Scope

In scope:

- Parse `ReviewFeedback`.
- Map feedback issue to target agent.
- Limit rework attempts.
- Supersede or reject old artifacts when a fix is produced.
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

## Artifact State Rules

- Rework creates replacement artifacts instead of mutating old ones.
- Old artifacts should become `superseded` when replaced.
- Artifacts explicitly rejected by the reviewer should become `rejected`.
- Downstream agents should read only `active` artifacts by default.
- Each feedback item has a max attempt count, default `2`.

## Tests

- Routes `missing_source` to Collector.
- Routes `unsupported_claim` to Analyst.
- Routes `format_violation` to Writer.
- Routes `missing_section` to Writer.
- Supersedes old artifacts after successful rework.
- Stops after max rework attempts.

## Done Criteria

- Reviewer rejection can lead to a bounded automatic rework.
- Infinite rework loops are impossible.
