# 09 Collector Agent

## Goal

Collect competitive intelligence evidence as structured `SourceArtifact`
objects. The current Collector is a research-plan agent: it attempts coverage
across the product, competitors, comparison dimensions, and the user's explicit
questions.

## Scope

In scope:

- Build query plans from company, competitors, market, and questions.
- Normalize common question dimensions such as audience, market share, pricing,
  features, positioning, use cases, limitations, and performance.
- Add industry-aware query expansions for reading/novel/product-market cases.
- Execute search/fetch through `ToolRuntime`.
- Score candidate URLs before fetch.
- Persist full cleaned fetch text through `content_ref`.
- Save compact source summaries plus metadata for downstream agents.
- Prioritize reviewer-generated `collector_rework_plan` items before generic
  collection.

Out of scope:

- Browser-rendered crawling.
- Paid search APIs.
- Long-term source credibility database.
- Letting Analyst/Writer/Reviewer fetch new evidence directly.

## Round Flow

```text
Round 1:
  Build coverage query plan, or targeted collector_rework_plan if present.

Round 2:
  Run batched web_search calls and record attempted:<entity>:<dimension> signals.

Round 3:
  Score URLs, dedupe domains, and run batched web_fetch calls.

Round 4:
  Filter relevance, extract summary, attach content metadata, save sources.

Round 5+:
  Refine missing coverage, or stop with sources_ready / coverage_partial.
```

## Source Metadata

Collector should preserve these metadata fields when available:

- `content_ref`: local full-text reference.
- `content_hash`: hash of persisted cleaned text.
- `char_count`: size of persisted text.
- `summary`: compact model/table preview.
- `covered_dimensions`: dimensions the source may help answer.
- `source_score`: URL/source quality hint.
- `extract_quality`: extraction quality hint.

Downstream agents use summaries for orientation and `content_ref` /
`content_excerpt` for evidence.

## Reviewer-Guided Rework

For blocking `missing_source` feedback, ReworkLoop writes a
`collector_rework_plan` into `RunContext.metadata`.

Collector must:

- read the plan before creating generic queries;
- generate focused searches for the feedback `entity`, `dimension`, and
  `question`;
- emit `targeted_rework_plan` in health signals;
- save any newly found evidence as normal `SourceArtifact` objects.

## Tests

- Query generation from request and competitors.
- URL dedupe and source scoring.
- Source artifact creation with metadata.
- Full-content metadata propagation.
- Attempted coverage signals.
- Targeted collector rework plan priority.
- Harness compatibility with fake tools.

## Done Criteria

- Collector attempts product, competitor, comparison, and user-question coverage.
- Fetch output can point to persisted full source text.
- Reviewer feedback can trigger targeted evidence collection.
- Network/tool failures remain observable through journal signals instead of
  silently approving weak evidence.
