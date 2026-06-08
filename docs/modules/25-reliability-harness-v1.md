# 25 Reliability Harness v1

## Goal

Strengthen the runtime harness beyond v0 budget and repeated-tool checks.

## Scope

In scope:

- Progress-aware stall detection.
- Retry policy with max retry count.
- Checkpoint recovery from persisted state.
- Tool result journaling.
- Health signals suitable for dashboard and golden replay.
- Duration and usage counters when available.

Out of scope:

- Distributed execution.
- Queue workers.
- Long-running scheduling.

## Tests

- Stalled read-only rounds produce a stall signal.
- Retryable tool/model errors retry within budget.
- Non-retryable errors abort with diagnostics.
- Recovery resumes from latest checkpoint.
- Dashboard shows health signals.

## Done Criteria

- Harness failures are diagnosable.
- Runs can recover from selected mid-run failures without starting over.
