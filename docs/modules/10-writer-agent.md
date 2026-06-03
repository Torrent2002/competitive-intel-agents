# 10 Writer Agent

## Goal

Convert analysis claims into a structured competitive intelligence report draft.

## Scope

In scope:

- Read analysis claims.
- Build required report sections.
- Preserve source references.
- Mark hypotheses separately from sourced facts.

Out of scope:

- New research.
- Claim verification.
- Reviewer routing.

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
- Separates hypotheses from sourced claims.

## Done Criteria

- Report draft can be reviewed by the Reviewer Agent.
- Report text is generated from structured claims, not raw unsourced prose.

