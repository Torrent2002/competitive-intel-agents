# 04 Artifact Store

## Goal

Provide structured shared memory between agents.

## Scope

In scope:

- Save and retrieve source artifacts.
- Save and retrieve analysis claims.
- Save and retrieve report drafts.
- Query artifacts by `run_id`.

Out of scope:

- Vector search.
- Ranking.
- Long-term memory.

## Public Interface

```python
class ArtifactStore:
    def save_source(self, artifact: SourceArtifact) -> None: ...
    def list_sources(self, run_id: str) -> list[SourceArtifact]: ...
    def save_claim(self, claim: AnalysisClaim) -> None: ...
    def list_claims(self, run_id: str) -> list[AnalysisClaim]: ...
    def save_report(self, report: ReportDraft) -> None: ...
    def get_latest_report(self, run_id: str) -> ReportDraft | None: ...
```

## Tests

- Save and list sources.
- Save and list claims.
- Get latest report.
- Keep artifacts isolated by `run_id`.

## Done Criteria

- Agents can communicate through structured artifacts.
- No agent needs to parse another agent's raw transcript to find sources or claims.

