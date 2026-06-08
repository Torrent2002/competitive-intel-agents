# 17 Golden Replay

## Goal

Replay curated cases and detect regressions without comparing exact prose.

Golden replay proves that the workflow remains reliable as prompts, tools, or
models change. It should catch evidence and control-flow regressions even when
the final report still sounds fluent.

## Scope

In scope:

- Golden input files.
- Expected schema files.
- Replay runner.
- Regression summary.

Out of scope:

- Human evaluation.
- Exact text matching.
- Production monitoring.

## Expected Case Layout

```text
tests/golden/
  case_01_single_competitor/
    input.json
    expected.json
```

## Expected Metrics v0

- Required sections present.
- Minimum source count.
- Source coverage.
- Maximum reviewer rejections.
- Maximum total rounds.
- Maximum tool calls.
- Minimum claim count.
- Claim source coverage ratio.
- Terminal harness/orchestrator decision.
- Rework attempt count.
- Required artifact lineage checks.

## Differentiation Metrics

Golden replay should measure workflow quality, not just final text:

- Did every factual claim have source ids?
- Did every report source id exist?
- Did reviewer feedback stay below the expected threshold?
- Did the pipeline avoid repeated-tool aborts?
- Did the run stay within round and tool-call budgets?
- Did rework preserve superseded/rejected artifact history?

## Tests

- Loads golden cases.
- Fails when required section is missing.
- Fails when source coverage drops.
- Reports metric deltas.
- Fails when a report sounds complete but has unsupported claims.
- Fails when a run passes by skipping Reviewer.
- Fails when artifact lineage is broken during rework.

## Done Criteria

- Golden replay can run in CI.
- Failures point to the specific metric that regressed.
- Golden replay demonstrates why this workflow is more robust than one-shot report generation.
