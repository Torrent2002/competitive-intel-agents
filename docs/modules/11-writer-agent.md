# 11 Writer Agent

## Goal

Convert analysis claims into a structured competitive intelligence report draft.

## Scope

In scope:

- Read analysis claims.
- Read active source metadata.
- Build required report sections.
- Preserve source references.
- Mark hypotheses separately from sourced facts.

Out of scope:

- New research.
- Claim verification.
- Reviewer routing.

## Inputs

- Active `AnalysisClaim` records.
- Active source metadata referenced by claims.
- Writer-scoped `ReviewFeedback` during rework.

## Required Sections v0

- Overview
- Feature comparison
- Pricing
- SWOT
- Sources

## Tests

- Produces all required sections.
- Includes source references for factual claims.
- Does not invent new source ids.
- Does not read raw web fetch output directly.
- Separates hypotheses from sourced claims.

## Done Criteria

- Report draft can be reviewed by the Reviewer Agent.
- Report text is generated from structured claims, not raw unsourced prose.
