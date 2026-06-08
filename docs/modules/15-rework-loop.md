# 15 Rework Loop

## Goal

Route reviewer feedback to the responsible agent and rerun only the needed part of the pipeline.

Rework is the main reason this workflow is more than a single-agent prompt. A
bad claim should not require throwing away the whole run; the system should
replace the affected artifact and rerun only downstream stages.

## Scope

In scope:

- Consume structured `ReviewFeedback`.
- Map feedback issue to target agent.
- Limit rework attempts.
- Supersede or reject old artifacts when a fix is produced.
- Re-run downstream agents after a fix.
- Preserve old artifacts for audit.
- Create replacement artifacts with valid lineage.
- Keep replacement artifacts inside the same `run_id` and artifact type.
- Continue downstream stages even when the target stage has no extra new artifact to produce after the replacement has already been created.

Out of scope:

- Complex planning.
- Human-in-the-loop editing.
- Parallel rework.
- Semantic rewriting quality beyond deterministic v0 replacement notes.

## Public Interface

```python
class ReworkLoop:
    def __init__(
        self,
        artifacts: ArtifactStore,
        harness: Harness,
        max_attempts: int = 2,
    ) -> None: ...

    def apply(self, context: RunContext, feedback: ReviewFeedback) -> ReworkResult: ...

def route_feedback(feedback: ReviewFeedback) -> list[AgentName]: ...
```

`ReworkResult` contains:

- `status`: `applied` or `max_attempts_exceeded`
- `attempts`
- `route`
- `replacement_artifact_ids`
- `final_decision`

## Routing v0

| Target Agent | Re-run Sequence |
|---|---|
| Collector | Collector -> Analyst -> Writer -> Reviewer |
| Analyst | Analyst -> Writer -> Reviewer |
| Writer | Writer -> Reviewer |

Reviewer feedback already carries `target_agent`; v0 trusts that routing target
instead of inferring intent from natural-language text.

## Artifact State Rules

- Rework creates replacement artifacts instead of mutating old ones.
- Old artifacts should become `superseded` when replaced.
- Artifacts explicitly rejected by the reviewer should become `rejected`.
- Downstream agents should read only `active` artifacts by default.
- Each feedback item has a max attempt count, default `2`.
- Replacement artifacts must share the same `run_id` and artifact type as the old artifact.
- Replacement artifacts must set `supersedes_id` to the old artifact id and advance `version`.
- Missing artifact references can still create a new source placeholder for Collector feedback, but cannot supersede a non-existent artifact.
- Upstream rework rejects stale downstream reports so Writer is forced to create a fresh report draft.
- Collector rework rejects stale active claims and reports because source changes can invalidate downstream evidence chains.
- Agent-generated ids must be monotonic across all artifact statuses to avoid duplicate ids after rejection or supersession.

## Current v0 Strategy

The loop is intentionally deterministic:

1. Check attempt budget for the exact `(issue, target_agent, target_artifact_id)` tuple.
2. Build a replacement artifact when the target artifact exists.
3. Save the replacement with `version + 1` and `supersedes_id`.
4. Mark the old artifact `superseded`.
5. Reject stale downstream artifacts.
6. Run the target stage and downstream stages through `RuntimeHarness`.

The replacement content is minimal in v0. For example, a missing report section is
filled from `ReviewFeedback.required_action`. Later model-backed rework can
replace this deterministic patching without changing routing or lineage rules.

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
- Rejects stale downstream reports after analyst/source rework.
- Preserves valid version lineage for replacement artifacts.

## Done Criteria

- Reviewer rejection can lead to a bounded automatic rework.
- Infinite rework loops are impossible.
- The final report can explain which feedback was applied and which artifact was replaced.
- Rework can be audited through artifact status and version chain.
