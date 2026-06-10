# 15 Rework Loop

## Goal

Route reviewer feedback to the responsible agent and rerun only the needed part
of the pipeline. For missing evidence, convert reviewer gaps into a targeted
collector research plan.

## Scope

In scope:

- Consume structured `ReviewFeedback`.
- Route feedback by `target_agent`.
- Prefer the most upstream blocking feedback.
- Limit rework attempts.
- Supersede or reject old artifacts when a fix is produced.
- Reject stale downstream artifacts.
- Re-run target and downstream agents through `RuntimeHarness`.
- Preserve old artifacts for audit.
- Keep replacement artifacts inside the same `run_id` and artifact type.
- Generate `collector_rework_plan` for blocking collector `missing_source`
  feedback.
- Preserve journal and model runtime while reworking so model-backed agents keep
  the same context quality.

Out of scope:

- Human-in-the-loop editing.
- Parallel rework planning.
- Letting downstream agents collect new evidence directly.

## Public Interface

```python
class ReworkLoop:
    def __init__(
        self,
        artifacts: ArtifactStore,
        harness: Harness,
        max_attempts: int = 2,
        journal: JournalStore | None = None,
        model_runtime: ModelRuntime | None = None,
    ) -> None: ...

    def apply(self, context: RunContext, feedback: ReviewFeedback) -> ReworkResult: ...

def route_feedback(feedback: ReviewFeedback) -> list[AgentName]: ...
```

`ReworkResult` contains:

- `status`: `applied` or `max_attempts_exceeded`;
- `attempts`;
- `route`;
- `replacement_artifact_ids`;
- `final_decision`.

## Routing

| Target Agent | Re-run Sequence |
|---|---|
| Collector | Collector -> Analyst -> Writer -> Reviewer |
| Analyst | Analyst -> Writer -> Reviewer |
| Writer | Writer -> Reviewer |
| Reviewer | Reviewer |

The orchestrator chooses the earliest blocking target when multiple feedback
items exist:

```text
collector -> analyst -> writer -> reviewer
```

## Targeted Collector Plan

For blocking `missing_source` feedback targeting Collector, ReworkLoop writes
focused plan items into:

```python
context.metadata["collector_rework_plan"]
```

Each item should preserve:

- `entity`;
- `dimension`;
- `question`;
- `required_action`;
- `issue`;
- `target_artifact_id`.

Collector must prioritize this plan before generic collection and emit
`targeted_rework_plan` in health signals.

## Artifact State Rules

- Rework creates replacement artifacts instead of mutating old ones.
- Old artifacts become `superseded` when replaced.
- Downstream stale artifacts become `rejected`.
- Downstream agents read only `active` artifacts by default.
- Each feedback key has a max attempt count.
- Replacement artifacts must share the same `run_id` and artifact type as the
  old artifact.
- Replacement artifacts must set `supersedes_id` when replacing an existing
  artifact.
- Missing virtual artifact references can create a new artifact id, but cannot
  supersede a non-existent artifact.
- Agent-generated ids must be monotonic across all artifact statuses.

## Terminal Status Semantics

- Unresolved collector `missing_source` blockers -> `needs_more_evidence`.
- Unresolved non-collector blockers -> `rework_failed`.
- Disabled or pending integrated rework -> `needs_rework`.
- Reviewer approval -> `approved`.

## Tests

- Routes feedback to target and downstream stages.
- Supersedes reports and reruns writer/reviewer.
- Stops after max attempts.
- Rejects stale downstream artifacts.
- Builds targeted collector plans from missing-source feedback.
- Preserves prior reports and feedback for reviewer context.

## Done Criteria

- Reviewer rejection can lead to bounded automatic rework.
- Missing evidence triggers targeted collector collection.
- Infinite rework loops are impossible.
- Artifact lineage remains auditable.
- Terminal status distinguishes evidence insufficiency from rework failure.
