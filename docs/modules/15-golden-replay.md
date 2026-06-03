# 15 Golden Replay

## Goal

Replay curated cases and detect regressions without comparing exact prose.

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

## Tests

- Loads golden cases.
- Fails when required section is missing.
- Fails when source coverage drops.
- Reports metric deltas.

## Done Criteria

- Golden replay can run in CI.
- Failures point to the specific metric that regressed.

