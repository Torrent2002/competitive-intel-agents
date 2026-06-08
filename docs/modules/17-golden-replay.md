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
- Structured metric failures.
- Deterministic fake pipeline replay.
- Store-based evidence and lineage evaluation.

Out of scope:

- Human evaluation.
- Exact text matching.
- Production monitoring.
- LLM-as-judge scoring.
- Live web/API dependency.

## Expected Case Layout

```text
tests/golden/
  case_01_single_competitor/
    input.json
    expected.json
```

## Public Interface

```python
@dataclass(frozen=True)
class ExpectedMetrics: ...

@dataclass(frozen=True)
class GoldenCase: ...

@dataclass(frozen=True)
class MetricFailure:
    metric: str
    expected: object
    actual: object
    message: str

@dataclass(frozen=True)
class GoldenCaseResult:
    case_name: str
    passed: bool
    metrics: dict[str, object]
    failures: list[MetricFailure]

class GoldenReplayRunner:
    def run_all(self) -> GoldenReplaySummary: ...
    def run_case(self, case: GoldenCase) -> GoldenCaseResult: ...

def load_golden_cases(root: str | Path) -> list[GoldenCase]: ...

def evaluate_golden_metrics(
    journal: JournalStore,
    artifacts: ArtifactStore,
    run_result: RunResult,
    expected: ExpectedMetrics,
) -> GoldenCaseResult: ...
```

Runner owns deterministic case execution. Evaluator owns metric calculation from
`JournalStore`, `ArtifactStore`, and `RunResult`. This keeps golden replay from
depending on report prose or agent internals.

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

## Expected Schema v0

```json
{
  "required_sections": ["Overview", "Feature comparison", "Pricing", "SWOT", "Sources"],
  "min_source_count": 2,
  "min_claim_count": 2,
  "min_claim_source_coverage_ratio": 1.0,
  "require_report_source_coverage": true,
  "max_reviewer_rejections": 0,
  "max_total_rounds": 12,
  "max_tool_calls": 4,
  "terminal_status": "approved",
  "terminal_decision": "stop",
  "require_reviewer": true,
  "max_rework_attempts": 0,
  "require_artifact_lineage": true
}
```

All fields are optional in code, but checked-in cases should be explicit so CI
failures are easy to interpret.

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
- Passes the checked-in deterministic fake pipeline case.

## Done Criteria

- Golden replay can run in CI.
- Failures point to the specific metric that regressed.
- Golden replay demonstrates why this workflow is more robust than one-shot report generation.
- Replay compares workflow metrics, not exact report prose.
- Golden cases are file-based and can be extended without changing code.
