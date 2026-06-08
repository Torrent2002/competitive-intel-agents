# 26 Integrated Rework Orchestration

## Goal

Make the Rework Loop part of normal orchestrator execution.

## Scope

In scope:

- Orchestrator option: `enable_rework=True`.
- Apply reviewer feedback automatically up to configured attempts.
- Rerun affected stage and downstream stages.
- Return final status:
  - `approved`
  - `needs_rework`
  - `rework_failed`
  - `aborted`
- Persist rework attempt metadata.

Out of scope:

- Human-in-the-loop editing.
- Parallel rework.
- Complex planning across multiple feedback items.

## Tests

- Reviewer feedback triggers ReworkLoop.
- Successful rework returns approved.
- Max attempts returns `rework_failed`.
- Artifact lineage remains valid.
- Journal shows original run and rework attempts.

## Done Criteria

- A normal run can repair fixable reviewer feedback without manual orchestration.
