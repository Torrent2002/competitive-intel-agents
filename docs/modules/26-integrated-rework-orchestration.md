# 模块 26：集成式 Rework Orchestration

## Goal

Integrate reviewer-driven rework into normal orchestrator execution.

## Scope

In scope:

- Detect reviewer `rework` decisions.
- Select the most upstream blocking feedback.
- Call `ReworkLoop` with shared artifact store, harness, journal, and model
  runtime.
- Rerun only the target stage and downstream stages.
- Preserve request, competitors, coverage gaps, source metadata, report history,
  and prior feedback for reviewer.
- Map unresolved feedback to explicit terminal statuses.

Out of scope:

- Human approval gates.
- Parallel multi-feedback planning.
- Automatic external search provider selection.

## Feedback Priority

```text
collector -> analyst -> writer -> reviewer
```

This prevents polishing a weak report before missing evidence and missing claims
are repaired.

## Terminal Status Mapping

- Latest reviewer approval -> `approved`.
- Integrated rework disabled or pending -> `needs_rework`.
- Unresolved collector `missing_source` feedback -> `needs_more_evidence`.
- Unresolved non-collector feedback -> `rework_failed`.
- Harness abort -> `aborted`.

## Collector Missing-Source Flow

```text
Reviewer missing_source feedback
  -> Orchestrator selects collector feedback
  -> ReworkLoop writes collector_rework_plan
  -> Collector runs targeted search/fetch
  -> Analyst reruns claims
  -> Writer reruns report
  -> Reviewer compares latest report with prior feedback/history
```

## Done Criteria

- Reviewer feedback is not a dead end.
- Missing evidence is routed to Collector with a focused plan.
- Analyst/Writer feedback reruns the correct downstream stages.
- Reviewer sees enough context to enforce the original user question.
- Terminal status explains the real outcome.
