# 11 Writer Agent

## Goal

Convert analysis claims into a structured competitive intelligence report draft.

The Writer turns structured claims into readable narrative. It does not perform
new research and does not invent factual claims outside the claim set.

## Scope

In scope:

- Read analysis claims.
- Read active source metadata.
- Build required report sections.
- Preserve source references.
- Mark hypotheses separately from sourced facts.
- Preserve claim ids and source ids in the draft structure so review can trace report text back to evidence.

Out of scope:

- New research.
- Claim verification.
- Reviewer routing.
- Creating new `AnalysisClaim` records.

## Inputs

- Active `AnalysisClaim` records.
- Active source metadata referenced by claims.
- Writer-scoped `ReviewFeedback` during rework.
- `ArtifactStore` dependency injected into the writer.

## Output Contract

- `ReportDraft.sections` must include all required sections.
- `ReportDraft.claim_ids` must reference only active claims used in the draft.
- `ReportDraft.source_ids` must be the union of sources referenced by those claims.
- Factual statements in report sections should be derived from `AnalysisClaim.text`.
- Hypotheses or recommendations must be clearly separated from sourced facts.

## Public Interface

```python
class WriterAgent(BaseAgent):
    name = "writer"

    REQUIRED_SECTIONS = (
        "Overview",
        "Feature comparison",
        "Pricing",
        "SWOT",
        "Sources",
    )

    def __init__(self, artifacts: ArtifactStore) -> None: ...
    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult: ...
```

## Round Flow v0

1. If an active report already exists, return `completed=True`.
2. Read active claims from `ArtifactStore`.
3. If no active claims exist, return `completed=False` with `missing_claims`.
4. Build all required sections from claim text and source ids.
5. Save one `ReportDraft` and return its id through `output_artifact_ids`.

The writer never returns tool calls in v0.

## Required Sections v0

- Overview
- Feature comparison
- Pricing
- SWOT
- Sources

## Report Ids

Report ids are deterministic in v0:

```text
report_{run_id}_{index:03d}
```

The first report is `report_{run_id}_001`. Rework will later create replacement
report ids and connect them through `supersedes_id`.

## Tests

- Produces all required sections.
- Includes source references for factual claims.
- Does not invent new source ids.
- Does not invent new claim ids.
- Does not introduce factual statements that are absent from active claims.
- Does not read raw web fetch output directly.
- Separates hypotheses from sourced claims.
- Skips inactive, superseded, or rejected claims.
- Runs through `RuntimeHarness` without tools.

## Done Criteria

- Report draft can be reviewed by the Reviewer Agent.
- Report text is generated from structured claims, not raw unsourced prose.
- Reviewer can map report issues back to claim ids or writer sections.
- Writer can be rerun safely without duplicating an existing active report.
