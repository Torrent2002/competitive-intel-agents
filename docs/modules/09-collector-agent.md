# 09 Collector Agent

## Goal

Collect competitive intelligence sources and save them as `SourceArtifact` records.

## Scope

In scope:

- Generate search queries from the run input.
- Use `web_search` and `web_fetch`.
- Save source artifacts.
- Avoid duplicate URLs.

Out of scope:

- Deep crawling.
- Source credibility scoring.
- Analyst conclusions.

## Inputs

- `RunContext`
- Company or product name.
- Market or competitor hints.

## Outputs

- `SourceArtifact` records.
- Progress signals.

## Tests

- Produces source artifacts from fake search results.
- Deduplicates repeated URLs.
- Stops when enough sources are collected.
- Does not produce analysis claims.

## Done Criteria

- Collector can run through the harness.
- Source artifacts include url, title, snippet, and retrieval timestamp.
