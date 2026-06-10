# 模块 23：结构化 Agent Prompt 与输出校验

## Goal

Give each agent a clear prompt contract and validate model output before it
enters the artifact workflow.

## Prompt Contract

Each agent prompt should define:

- role and responsibility;
- inputs it receives;
- outputs it must produce;
- evidence access rules;
- escalation target when blocked;
- self-check criteria.

## Agent-Specific Requirements

### Collector

Inputs:

- user request;
- competitors;
- questions and normalized dimensions;
- prior tool results;
- optional `collector_rework_plan`.

Outputs:

- search/fetch tool calls;
- source JSON when model extraction is used;
- coverage and attempted signals.

Rules:

- attempt product, competitor, comparison, and question coverage;
- prioritize reviewer-targeted research plans;
- preserve `content_ref` metadata when available.

### Analyst

Inputs:

- active sources;
- source metadata;
- `content_ref`;
- `content_excerpt`;
- user request;
- prior feedback.

Outputs:

- `AnalysisClaim` JSON with `source_ids`.

Rules:

- every factual claim needs at least one source id;
- use source excerpts/refs, not hidden knowledge;
- do not infer beyond the evidence.

### Writer

Inputs:

- active claims;
- active sources;
- source metadata and excerpts;
- user request;
- prior feedback;
- report history.

Outputs:

- `ReportDraft` sections JSON.

Rules:

- answer the user's questions explicitly;
- cite claim/source ids in prose;
- do not repeat one source summary across every section;
- do not invent pricing, market share, or competitor facts.

### Reviewer

Inputs:

- latest report;
- claims;
- sources;
- source metadata;
- coverage gaps;
- original request and competitors;
- report history;
- prior_review_feedback.

Outputs:

- approval decision, or routable `ReviewFeedback`.

Rules:

- evaluate against the original user request;
- check competitor coverage;
- reject source-summary-only reports;
- keep unresolved historical blocking feedback blocking;
- route feedback to the earliest responsible agent.

## Evidence Access

Prompt context may include:

- source summaries/snippets;
- `content_ref`;
- `content_excerpt` loaded from persisted content;
- source quality and coverage metadata.

Snippets are previews. `content_ref` / `content_excerpt` are the evidence path
for deeper analysis.

## Validation

| Agent | Validator |
|---|---|
| Collector | `sources` must be a list |
| Analyst | each claim must contain `source_ids` |
| Writer | `sections` must be a dict |
| Reviewer | feedback must contain `issue`, `target_agent`, `target_artifact_id`, `message`, and `required_action` |

Invalid model output falls back to deterministic behavior instead of corrupting
the artifact store.

## Done Criteria

- Agent prompts describe role, inputs, outputs, evidence access, escalation, and
  self-checks.
- Runtime context supplies the data the prompts require.
- Reviewer can see request, competitors, coverage gaps, source metadata, report
  history, and prior feedback.
- Analyst and Writer are explicitly told to use full-source evidence through
  `content_ref` / `content_excerpt`.
