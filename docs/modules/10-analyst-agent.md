# 10 Analyst Agent

## Goal

Turn collected sources into sourced competitive analysis claims.

The Analyst is not a second collector. Its job is to transform evidence into
structured claims while preserving source provenance.

## Scope

In scope:

- Read `SourceArtifact` records.
- Produce `AnalysisClaim` records.
- Attach source ids to each claim.
- Assign confidence.
- Preserve the boundary that every claim is downstream of active sources.
- Incorporate analyst-targeted reviewer feedback during rework.

Out of scope:

- Final report writing.
- Web search or fetching.
- Reviewer approval.
- Writing narrative report sections.

## Inputs

- `SourceArtifact` records.
- Analysis task from orchestrator.
- Analyst-scoped `ReviewFeedback` during rework.
- `ArtifactStore` dependency injected into the analyst.

## Outputs

- `AnalysisClaim` records.

## Public Interface

```python
class AnalystAgent(BaseAgent):
    name = "analyst"

    def __init__(self, artifacts: ArtifactStore, target_claims: int = 2) -> None: ...
    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult: ...
```

## Round Flow v0

1. Read active sources from `ArtifactStore`.
2. If no active sources exist, return `completed=False` with `missing_sources`.
3. Read active claims and skip sources that already have an active claim.
4. Create deterministic `AnalysisClaim` records until `target_claims` is reached or sources are exhausted.
5. Return saved claim ids through `output_artifact_ids`.

The analyst never returns tool calls in v0.

## Provenance Rules

- Every `AnalysisClaim` must include at least one `source_id`.
- Each referenced source id must exist as an active `SourceArtifact`.
- Analyst must not create claims from hidden model context or raw prompt memory without source ids.
- Analyst must not call web tools. Missing evidence should become reviewer feedback routed to Collector.
- Rework creates replacement claim ids and links old claims with `supersedes_id`; it never overwrites old claim ids.

## Claim Quality v0

- `confidence` should be `high`, `medium`, or `low`.
- `reasoning` should explain why the listed sources support the claim.
- Claims should be atomic enough for reviewer feedback to target one artifact id.

## Claim Ids

Claim ids are deterministic in v0:

```text
claim_{run_id}_{index:03d}
```

This keeps tests and journal output readable. Rework will later create
replacement claim ids and connect them through `supersedes_id`.

## Tests

- Produces claims with source ids.
- Rejects or skips claims without sources.
- Does not call web tools.
- Reads only active source artifacts.
- Emits completion when required sections have enough claims.
- Rejects references to inactive, rejected, or unknown source ids.
- Rework creates replacement claims rather than mutating old ones.
- Skips sources that already have active claims.
- Runs through `RuntimeHarness` without tools.

## Done Criteria

- Analyst output can be traced back to collector sources.
- Writer can consume claims without reading raw web pages.
- Reviewer can target individual claims for rework.
