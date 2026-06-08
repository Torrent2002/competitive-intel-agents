# 29 Golden Suite Expansion and CI

## Goal

Expand golden replay from one smoke case into a CI-ready regression suite.

## Scope

In scope:

- More golden cases:
  - single competitor;
  - multi competitor;
  - sparse sources;
  - reviewer rejection;
  - rework success;
  - tool failure/retry.
- CLI command:
  - `competitive-intel golden --root tests/golden`
- CI-friendly summary and exit codes.
- Metric deltas in failure output.

Out of scope:

- Human scoring.
- Exact prose comparison.
- Provider-backed golden runs by default.

## Tests

- Golden CLI exits non-zero on regression.
- Failure output names the metric.
- Fake mode is deterministic in CI.
- Golden fixtures are schema-validated.

## Done Criteria

- Golden replay can run as a required CI check.
- Regression failures are actionable.
