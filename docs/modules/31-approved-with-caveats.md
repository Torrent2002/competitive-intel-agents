# 模块 31：approved_with_caveats — 软终态与 reviewer 严格性

## Goal

Allow runs whose report is deliverable but still carries non-evidence
reviewer concerns to ship as a positive terminal state with explicit
caveats, instead of being misclassified as `rework_failed`.

## Scope

In scope:

- New `RunResult.caveats: list[ReviewFeedback]` field on the data model
- New `approved_with_caveats` status returned by `Orchestrator`
- CLI summary block + Web dashboard styling and section
- Two unit tests covering both directions of the new branching rule

Out of scope:

- Reviewer producing `severity != "blocking"` feedback (still default-blocking)
- Writing caveats into `ReportDraft.sections` or any artifact

## Design

### Status decision

`Orchestrator._status_for_unresolved_feedback(feedback_items, report_id)`:

```
no feedback                                            -> rework_failed
feedback all (collector + missing_source + blocking)   -> needs_more_evidence
report_id is not None AND
  no item is (collector + missing_source)              -> approved_with_caveats
otherwise                                              -> rework_failed
```

The asymmetry is deliberate:

- `missing_source` failures cannot become caveats — they mean the report
  has no evidentiary footing.
- `report_id is None` cannot become caveats — there is nothing to ship.

### Field separation

When `status == "approved_with_caveats"`:

- `RunResult.review_feedback` is **empty**
- residual feedback lives in `RunResult.caveats`

This preserves the prior contract that `review_feedback != []` implies
the run is unfinished, so existing consumers (CLI, web flow renderer,
future SDKs) keep their conditional logic intact.

### Surfacing

- **CLI** (`cli/__init__.py`): summary block prints `Caveats: N` and a
  bulleted list with severity, issue, target, message, and required
  action.
- **Web** (`web/__init__.py`):
  - Status pill: `.status.approved_with_caveats { background:#fef9c3;
    color:#854d0e; }`
  - Display-status guard expanded so `approved_with_caveats` survives
    snapshot derivation (which only reads from journal events and
    cannot recognise the new state on its own).
  - Agent flow marks the terminal agent `completed`, not `aborted`.
  - A dedicated `Reviewer Caveats (N)` section renders below the report
    body.

## Tests

`tests/unit/test_orchestrator.py`:

1. `test_orchestrator_returns_approved_with_caveats_when_report_survives`
   — writer stub persists a report each round; reviewer points at a
   non-existent artifact id so ReworkLoop's prepare path takes the safe
   `ArtifactNotFoundError` branch; outer rework budget is exhausted;
   asserts `status == "approved_with_caveats"`, `caveats` non-empty,
   `review_feedback == []`.

2. `test_orchestrator_keeps_rework_failed_when_no_report_was_produced`
   — writer stub never persists a report; same blocker pattern; asserts
   `status == "rework_failed"`, `caveats == []`.

`tests/unit/test_web_dashboard.py::test_render_workflow_map_shows_agent_and_rework_paths`
updated to assert presence of the new status string and the rewritten
contract sentence.

## Backward compatibility

- Existing `rework_failed` semantics narrow: only triggered when the
  pipeline genuinely cannot deliver. Existing tests expecting
  `rework_failed` for "no report" paths still pass (the new branch
  requires `report_id is not None`).
- Existing `approved` and `needs_more_evidence` paths unchanged.
- `review_feedback` field shape unchanged; new `caveats` field is
  additive with `default_factory=list` so deserialisation of older
  serialised RunResult objects yields `[]`.
