# 模块 33：全局运行超时

## Goal

Bound the wall-clock cost of a single run so a stuck collector loop or
hung model call cannot leave a `running` zombie indefinitely. Surface
the timeout as a deliverable result rather than a hard kill whenever
partial work is salvageable.

## Scope

In scope:

- New `Orchestrator.__init__` parameters `max_wall_time: float | None
  = 600.0` and `time_provider: Callable[[], float] | None = None`
- Deadline checks at every agent boundary (entry + exit) and at the
  top of each integrated-rework iteration
- Status mapping: `report_id is not None → approved_with_caveats`,
  otherwise `aborted`. `error` field carries `"global_timeout"` in
  both cases
- Synthetic `ReviewFeedback` caveat with `issue=format_violation`,
  `severity=advisory`, `blocking=False`
- Web dashboard: `_make_web_orchestrator` reads `CIA_MAX_RUN_SECONDS`
  env var (`0` disables the deadline, unset → 600s default,
  unparseable → 600s)
- 3 unit tests in `tests/unit/test_orchestrator.py`

Out of scope:

- Per-round / per-model-call deadline checks — `RuntimeHarness` and
  `ModelRuntime` are not instrumented; their default tests do not
  model time
- New status enum values; `approved_with_caveats` and `aborted` are
  reused
- New `VALID_REVIEW_ISSUES` entries — `format_violation` is
  semantically closest and avoids touching the reviewer prompt /
  validator surface

## Design

### Deadline check function

```python
def _timeout_result_if_due(self, context) -> RunResult | None:
    if self._deadline is None:
        return None
    if self._time_provider() < self._deadline:
        return None
    report_id = self._latest_report_id(context.run_id)
    timeout_caveat = ReviewFeedback(
        issue="format_violation",
        target_agent="reviewer",
        target_artifact_id=f"run_{context.run_id}_deadline",
        message="Run exceeded the configured wall-clock budget ...",
        required_action="Review remaining gaps; rerun with a larger ...",
        severity="advisory",
        blocking=False,
    )
    if report_id is not None:
        return RunResult(
            run_id=context.run_id,
            status="approved_with_caveats",
            report_id=report_id,
            caveats=[timeout_caveat],
            error="global_timeout",
        )
    return RunResult(
        run_id=context.run_id,
        status="aborted",
        error="global_timeout",
    )
```

### Check points in `run()`

1. Before each agent in `_build_agents()`
2. After the last agent (so a deadline that trips during the reviewer
   round still returns a timeout result instead of `approved`)
3. At the top of every integrated-rework iteration (in
   `_apply_integrated_rework`)

### Time provider injection

`time_provider` defaults to `time.monotonic`. Tests pass an iterator
adapter:

```python
ticks = iter([0.0, 10_000.0, 10_001.0])
orchestrator = Orchestrator(
    max_wall_time=1.0,
    time_provider=lambda: next(ticks),
    ...,
)
```

Each call advances time deterministically — no `time.sleep`, no
`mock.patch`.

### Web env var contract

```
CIA_MAX_RUN_SECONDS unset       → 600s (default)
CIA_MAX_RUN_SECONDS=300         → 300s
CIA_MAX_RUN_SECONDS=0           → no deadline
CIA_MAX_RUN_SECONDS=garbage     → 600s (parse failure → default)
```

## Tests

`tests/unit/test_orchestrator.py`:

1. `test_orchestrator_returns_aborted_when_timeout_before_any_report`
   — deadline trips on the first agent boundary; harness writes no
   report; asserts `status="aborted"`, `error="global_timeout"`,
   `report_id is None`, `caveats == []`

2. `test_orchestrator_returns_caveats_when_timeout_after_report_exists`
   — writer persists a report, deadline then trips before reviewer
   runs; asserts `status="approved_with_caveats"`,
   `error="global_timeout"`, single caveat with
   `issue="format_violation"` and `"wall-clock budget"` in message,
   `harness.calls` does not include `"reviewer"`

3. `test_orchestrator_no_timeout_when_max_wall_time_is_none` —
   passing `None` disables the deadline entirely; the canonical
   end-to-end pipeline yields the same `status="approved"` it always did

## Backward compatibility

- All 12 pre-existing orchestrator tests pass without modification
  because they don't pass `max_wall_time` and the default 600s is
  effectively infinite for sub-second test pipelines
- `RunResult.error` field already exists and is widely consumed; the
  new `"global_timeout"` value is additive
- Existing `approved_with_caveats` consumers (CLI summary block, web
  caveats panel, [[31-approved-with-caveats]] guards) handle the
  timeout caveat without modification — it's just another
  `ReviewFeedback` with `blocking=False`

## Related

- [[31-approved-with-caveats]] — the soft terminal state the timeout
  branch reuses
- [[32-model-retry]] — bounds the per-call retry cost so retries don't
  silently consume the wall-clock budget
