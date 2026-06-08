# 15 Rework Loop

## Goal

Route reviewer feedback to the responsible agent and rerun only the needed part of the pipeline.

Rework is the main reason this workflow is more than a single-agent prompt. A
bad claim should not require throwing away the whole run; the system should
replace the affected artifact and rerun only downstream stages.

## Scope

In scope:

- Parse `ReviewFeedback`.
- Map feedback issue to target agent.
- Limit rework attempts.
- Supersede or reject old artifacts when a fix is produced.
- Re-run downstream agents after a fix.
- Preserve old artifacts for audit.
- Create replacement artifacts with valid lineage.

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
- Replacement artifacts must share the same `run_id` and artifact type as the old artifact.
- Replacement artifacts must set `supersedes_id` to the old artifact id and advance `version`.

## Rework Differentiation

- `missing_source` should rerun Collector and then rerun downstream Analyst, Writer, Reviewer.
- `unsupported_claim` and `weak_inference` should rerun Analyst and downstream stages.
- `format_violation`, `missing_section`, and `unclear_writing` should rerun Writer and Reviewer.
- Rework attempts should append journal events instead of overwriting the prior trail.
- A bounded rework failure should produce an explicit run status, not an endless loop.

## Tests

- Routes `missing_source` to Collector.
- Routes `unsupported_claim` to Analyst.
- Routes `format_violation` to Writer.
- Routes `missing_section` to Writer.
- Supersedes old artifacts after successful rework.
- Stops after max rework attempts.
- Leaves rejected and superseded artifacts available for audit.
- Reruns only the affected stage and downstream stages.

## Done Criteria

- Reviewer rejection can lead to a bounded automatic rework.
- Infinite rework loops are impossible.
- The final report can explain which feedback was applied and which artifact was replaced.
