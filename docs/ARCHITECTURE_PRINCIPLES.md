# Architecture Principles

## Positioning

This project is an evidence-first competitive intelligence workflow, not a
generic multi-agent demo.

A single capable agent can search, analyze, and write a report. The reason this
project uses role-bounded agents is not raw model capability. The reason is
engineering control:

- intermediate artifacts are structured and inspectable;
- factual claims are source-backed;
- failures can be routed to the responsible stage;
- rework is bounded and local;
- every round is journaled and replayable;
- quality can be regression-tested without exact prose matching.

## Runtime vs Workflow

An agent runtime can execute tools and call subagents. This project sits one
layer above that runtime.

| Layer | Responsibility |
|---|---|
| Agent runtime | Execute model calls, tools, and agent loops |
| This workflow | Define domain contracts, role boundaries, source-backed artifacts, reviewer feedback, rework, replay metrics |

The runtime is the engine. This project is the domain-specific production line.

## Non-Negotiable Invariants

### 1. Evidence Before Narrative

Collector writes `SourceArtifact`.
Analyst writes `AnalysisClaim`.
Writer writes `ReportDraft`.
Reviewer writes `ReviewFeedback`.

Final prose must be downstream of structured evidence. It must not be the only
place where facts live.

Collected evidence has two layers:

- a compact `SourceArtifact` summary for fast inspection and tables;
- a persisted full-text `content_ref` for downstream agents that need the
  complete cleaned page text.

Snippets and summaries are navigation aids, not the source of truth.

### 2. Claims Must Carry Sources

Every factual `AnalysisClaim` must include at least one `source_id`.
Reports should reference claim ids and source ids instead of inventing facts from
hidden prompt context.

### 3. Role Boundaries Are Product Semantics

Collector may use web tools.
Analyst, Writer, and Reviewer do not use web tools in v0.

This is not because they are technically unable to use tools. It is because the
workflow needs a clear evidence path: source collection first, analysis second,
writing third, review last.

Analyst, Writer, and Reviewer may receive `content_ref`, `content_excerpt`, and
source metadata produced by Collector. They can reason over collected evidence,
but they should not create new evidence outside the collection boundary.

### 4. Artifacts Are Immutable By Id

Rework creates a new artifact id and links it with `supersedes_id`.
Duplicate artifact ids are errors.

This keeps old conclusions inspectable and makes review/rework explainable.

### 5. Reviewer Feedback Must Be Routable

Reviewer output must name:

- issue type;
- target agent;
- target artifact id;
- required action.

Feedback that cannot be routed is prose, not workflow control.

For missing evidence, reviewer feedback should also carry the relevant `entity`,
`dimension`, and original `question` when possible. ReworkLoop can turn that
structured gap into a targeted collector research plan instead of rerunning the
generic search flow.

### 6. Journal Is The Audit Trail

Every harness round writes a `RoundEvent`.
Dashboard, replay, and debugging should read journal events instead of scraping
agent transcripts.

### 7. Golden Replay Uses Metrics, Not Exact Prose

Generated wording can vary. Regression tests should focus on:

- source count;
- claim source coverage;
- required sections;
- reviewer rejection counts;
- total rounds;
- tool calls;
- terminal decision.

### 8. Rework Is Targeted, Not Generic

The system should first repair the earliest failed stage:

```text
collector -> analyst -> writer -> reviewer
```

If Reviewer says the report lacks competitor evidence, the next Collector pass
should receive that exact gap as a research plan. It should not blindly repeat
the original broad collection plan unless no structured gap is available.

## Interview Framing

If asked "could a single agent do this?", the correct answer is:

> Yes, a single agent can produce a report. This project is about making that
> work reliable: structured evidence, role-bounded permissions, reviewer-driven
> rework, journal replay, and regression metrics. The multi-agent shape is an
> implementation of those reliability goals, not the goal itself.
