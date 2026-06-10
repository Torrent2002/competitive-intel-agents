# Agent Collaboration Contract

This document defines the shared contract between the orchestrator, agents,
artifacts, reviewer feedback, run statuses, and the web workflow map.

The goal is to keep competitive analysis auditable: every stage has a bounded
responsibility, every artifact has an owner, and every rework request routes to
the earliest agent that can fix the underlying problem.

## Roles and Artifacts

| Component | Inputs | Outputs | Responsibility |
|---|---|---|---|
| User Request | Company, competitors, market, questions | `CompetitiveIntelRequest` | Defines the analysis scope and acceptance criteria. |
| Orchestrator | Request, agent profiles, stores, journal | `RunContext`, `RunResult`, journal sequence | Runs the DAG, applies bounded rework, and decides terminal status. |
| Collector | Request, prior tool results, reviewer feedback, optional `collector_rework_plan` | `SourceArtifact`, coverage signals, source metadata | Attempts to collect product, competitor, and question-dimension evidence. |
| Analyst | Active sources, request, reviewer feedback, `content_ref` / `content_excerpt` | `AnalysisClaim` | Converts sources into grounded claims with `source_ids`. |
| Writer | Active claims, active sources, request, reviewer feedback, `content_ref` / `content_excerpt`, report history | `ReportDraft` | Produces report sections from claims without inventing unsupported facts. |
| Reviewer | Report, claims, sources, request, coverage gaps, source metadata, report history, prior feedback | `ReviewFeedback` or approval | Checks grounding, user-question coverage, competitor coverage, and clarity. |

## Forward Flow

The normal path is:

```text
User Request
  -> Orchestrator
  -> Collector
  -> Analyst
  -> Writer
  -> Reviewer
  -> approved
```

The orchestrator may stop earlier if an agent aborts, or it may enter a rework
loop if reviewer feedback identifies a blocking gap.

## Evidence Access Contract

Collector owns evidence acquisition. Every successful fetch should preserve both
review-friendly metadata and the full cleaned text:

| Field | Purpose |
|---|---|
| `summary` / `snippet` | Compact preview for tables and quick model triage. |
| `content_ref` | Local reference to the full cleaned source text. |
| `content_hash` | Stable hash for dedupe and audit. |
| `char_count` | Size of the persisted source text. |
| `content_excerpt` | Prompt-context excerpt read from `content_ref` for downstream agents. |
| `covered_dimensions` | Collector's best estimate of which research dimensions the source may cover. |
| `source_score` / `extract_quality` | Quality hints used for ranking and diagnostics. |

Analyst and Writer must treat snippets as insufficient when a `content_ref` is
available. Reviewer should reject reports that only recycle source summaries or
keywords when the original user question requires deeper evidence.

## Status Semantics

| Status | Meaning | User-facing interpretation |
|---|---|---|
| `approved` | Reviewer accepted the latest report. | The run produced a source-backed report that satisfies current gates. |
| `needs_rework` | Reviewer produced feedback and integrated rework is disabled or pending. | The run is not final; a specific agent must fix feedback. |
| `needs_more_evidence` | Bounded rework ended with unresolved collector `missing_source` blockers. | The system needs more evidence or better collection inputs before the report can be trusted. |
| `rework_failed` | Bounded rework ended with unresolved non-collector blockers. | The agent logic failed to repair claims, writing, or review issues within budget. |
| `aborted` | An agent returned `abort` or exceeded reliability limits. | Execution stopped due to runtime/tool/round-budget failure. |
| `running` | Background web run is still executing. | The run detail page may auto-refresh and show the active agent. |

Only `approved` is considered a successful final report. `needs_more_evidence`
is not a crash; it is an explicit evidence insufficiency outcome.

## Reviewer Feedback Contract

Reviewer feedback is the only supported way to ask an upstream agent to fix an
artifact or missing coverage.

Required fields:

| Field | Purpose |
|---|---|
| `issue` | One of `missing_source`, `unsupported_claim`, `weak_inference`, `unclear_writing`, `format_violation`, `missing_section`. |
| `target_agent` | The earliest agent that can fix the root cause. |
| `target_artifact_id` | The artifact or coverage key that needs repair. |
| `message` | Human-readable reason for rejection. |
| `required_action` | Concrete action the target agent should take. |

Optional structured fields:

| Field | Purpose |
|---|---|
| `severity` | Defaults to `blocking`; future values may allow advisory feedback. |
| `blocking` | Defaults to `true`; blocking feedback prevents approval. |
| `entity` | Product or competitor involved in the gap. |
| `dimension` | User question or comparison dimension involved in the gap. |
| `question` | Original user question that triggered the feedback. |

## Feedback Routing

Feedback always routes to the earliest agent that can repair the root cause:

| Feedback target | Route |
|---|---|
| `collector` | Collector -> Analyst -> Writer -> Reviewer |
| `analyst` | Analyst -> Writer -> Reviewer |
| `writer` | Writer -> Reviewer |
| `reviewer` | Reviewer |

When multiple feedback items exist, the orchestrator chooses the most upstream
blocking target first:

```text
collector -> analyst -> writer -> reviewer
```

This prevents the system from polishing a report before missing evidence or
missing claims have been repaired.

## Targeted Collector Rework

When Reviewer emits blocking `missing_source` feedback for Collector, ReworkLoop
turns the structured gap into `RunContext.metadata["collector_rework_plan"]`.
The plan contains focused items such as:

```json
{
  "entity": "起点阅读",
  "dimension": "market_share",
  "question": "比较番茄小说与起点阅读的用户规模和市场份额",
  "required_action": "Collect competitor market-share evidence"
}
```

Collector must prioritize this plan before generic collection. The follow-up run
should emit a `targeted_rework_plan` signal so the journal shows that the retry
was driven by reviewer feedback, not by another broad search pass.

If targeted collector rework still cannot produce sufficient evidence within the
attempt budget, the terminal status should be `needs_more_evidence`, not a vague
success or generic failure.

## Report History and Prior Feedback

Reviewer receives:

- the latest report;
- prior report drafts for comparison;
- prior reviewer feedback;
- source metadata and coverage gaps;
- the original user request and competitor list.

Approval means the latest report resolves all blocking historical feedback that
still applies. If a prior collector gap is still visible, Reviewer should keep it
blocking and route it back upstream.

## Examples

### Missing competitor evidence

Reviewer feedback:

```text
issue: missing_source
target_agent: collector
entity: Competitor A
dimension: competitor coverage
```

Route:

```text
Reviewer -> Collector -> Analyst -> Writer -> Reviewer
```

If this remains unresolved after bounded attempts, the run ends as
`needs_more_evidence`.

### Sources exist but no claim uses them

Reviewer feedback:

```text
issue: unsupported_claim
target_agent: analyst
entity: Competitor A
dimension: competitor claims
```

Route:

```text
Reviewer -> Analyst -> Writer -> Reviewer
```

If unresolved after bounded attempts, the run ends as `rework_failed`.

### Claims exist but report omits the answer

Reviewer feedback:

```text
issue: missing_section
target_agent: writer
dimension: pricing
question: pricing, collaboration
```

Route:

```text
Reviewer -> Writer -> Reviewer
```

If unresolved after bounded attempts, the run ends as `rework_failed`.

## Frontend Contract

The web dashboard should reflect the same contract:

1. The run list links to the workflow map.
2. Run detail shows four fixed agents so collaboration is visible before tables.
3. Running agents display thinking and border animation.
4. `needs_more_evidence` highlights collector-oriented rework instead of showing
   a generic failure.
5. `/workflow` shows the primary path, possible rework paths, terminal outcomes,
   and this contract summary.
6. Source tables should expose content metadata such as `content_ref`,
   `char_count`, and `covered_dimensions` when present.

The frontend should not invent a separate state machine. It should derive display
state from `RunResult.status`, `RoundEvent.decision`, and `ReviewFeedback`.
