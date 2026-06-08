# 09 Collector Agent

## Goal

Collect competitive intelligence sources and save them as `SourceArtifact` records.

## Scope

In scope:

- Generate search queries from the run input.
- Request `web_search` and `web_fetch` through `ToolCall` objects.
- Consume prior `ToolResult` records from `AgentState.memory["tool_results"]`.
- Save source artifacts.
- Avoid duplicate URLs.
- Stop when the configured source target is reached.

Out of scope:

- Deep crawling.
- Source credibility scoring.
- Analyst conclusions.

## Inputs

- `RunContext`
- `AgentState`
- Company or product name.
- Market or competitor hints.
- Prior tool results from harness-managed agent memory.
- `ArtifactStore` dependency injected into the collector.

## Outputs

- `SourceArtifact` records.
- `ToolCall` requests for search/fetch.
- Progress signals.

## Public Interface

```python
class CollectorAgent(BaseAgent):
    name = "collector"

    def __init__(self, artifacts: ArtifactStore, target_sources: int = 2) -> None: ...
    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult: ...
```

## Round Flow v0

1. If enough active sources already exist in `ArtifactStore`, return `completed=True`.
2. If there are no prior tool results, request one `web_search` call using company, market, competitors, and questions.
3. If prior tool results contain search results, deduplicate URLs and request `web_fetch` calls for URLs not already saved.
4. If prior tool results contain fetch results, save each unique URL as a `SourceArtifact`.
5. Return saved source ids through `output_artifact_ids`.

The collector never executes tools directly. Runtime execution remains owned by
the harness.

## Source Ids

Source ids are deterministic in v0:

```text
source_{run_id}_{index:03d}
```

This keeps tests stable and makes journal output readable. A later artifact id
service can replace this if concurrent collectors are introduced.

## Deduplication Rules

- Duplicate URLs inside one search result batch are fetched once.
- URLs already saved as active `SourceArtifact` records are skipped.
- Duplicate fetch results do not overwrite existing artifacts.

## Tests

- Produces source artifacts from fake search results.
- Deduplicates repeated URLs.
- Stops when enough sources are collected.
- Does not produce analysis claims.
- Builds search query from company, market, competitors, and questions.
- Runs through `RuntimeHarness` with fake tools.

## Done Criteria

- Collector can run through the harness.
- Source artifacts include url, title, snippet, and retrieval timestamp.
- Collector does not depend directly on `ToolRuntime`.
- Collector only writes source artifacts, not claims or reports.
