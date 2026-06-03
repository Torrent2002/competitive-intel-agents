# 10 Analyst Agent

## Goal

Turn collected sources into sourced competitive analysis claims.

## Scope

In scope:

- Read `SourceArtifact` records.
- Produce `AnalysisClaim` records.
- Attach source ids to each claim.
- Assign confidence.

Out of scope:

- Final report writing.
- Web search or fetching.
- Reviewer approval.

## Inputs

- `SourceArtifact` records.
- Analysis task from orchestrator.
- Analyst-scoped `ReviewFeedback` during rework.

## Outputs

- `AnalysisClaim` records.

## Tests

- Produces claims with source ids.
- Rejects or skips claims without sources.
- Does not call web tools.
- Reads only active source artifacts.
- Emits completion when required sections have enough claims.

## Done Criteria

- Analyst output can be traced back to collector sources.
- Writer can consume claims without reading raw web pages.
