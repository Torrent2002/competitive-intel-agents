# 05 Artifact Store

## Goal

Provide structured shared memory between agents.

## Scope

In scope:

- Save and retrieve source artifacts.
- Save and retrieve analysis claims.
- Save and retrieve report drafts.
- Query artifacts by `run_id`.
- Query only active artifacts by default.
- Mark artifacts as superseded or rejected during rework.

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
    def list_claims(self, run_id: str, status: ArtifactStatus = "active") -> list[AnalysisClaim]: ...
    def save_report(self, report: ReportDraft) -> None: ...
    def get_latest_report(self, run_id: str) -> ReportDraft | None: ...
    def mark_superseded(self, artifact_id: str, replacement_id: str) -> None: ...
    def mark_rejected(self, artifact_id: str, reason: str) -> None: ...
```

## Versioning Rules

- Rework never overwrites an artifact in place.
- Artifact ids are immutable. Saving an artifact id that already exists raises `DuplicateArtifactError`.
- A replacement artifact should use a new id.
- A replacement artifact should set `version` to a greater number than the previous artifact.
- A replacement artifact should set `supersedes_id` to the previous artifact id.
- `mark_superseded(old_id, replacement_id)` validates that both artifacts exist, share the same `run_id`, share the same artifact type, and that the replacement points back to `old_id`.
- Default list methods should return only `active` artifacts unless a different status is requested.
- Rejected artifacts stay available for audit but should not be consumed by downstream agents.
- Returned artifacts must expose their current store status. If an artifact is listed through `status="superseded"` or `status="rejected"`, its model `status` field must match.
- In-memory and SQLite implementations must follow the same duplicate, status, and lineage semantics.

## Error Types

- `ArtifactNotFoundError`: raised when a mutation references an unknown artifact id.
- `DuplicateArtifactError`: raised when saving an artifact id that already exists.
- `InvalidArtifactLineageError`: raised when a replacement crosses run/type boundaries, lacks the correct `supersedes_id`, or does not advance `version`.

## Tests

- Save and list sources.
- Save and list claims.
- Get latest report.
- Keep artifacts isolated by `run_id`.
- Mark old claims as superseded after rework.
- Exclude rejected artifacts from default reads.
- Reject duplicate artifact ids.
- Return model objects with current `status` after rejection or supersession.
- Reject supersede operations across different runs or artifact types.
- Reject replacements without the correct `supersedes_id` or forward version.

## Done Criteria

- Agents can communicate through structured artifacts.
- No agent needs to parse another agent's raw transcript to find sources or claims.
- Rework cannot accidentally leave rejected claims active for the Writer.
- Rework cannot accidentally connect artifacts from different runs or artifact types.
- Tests exercise both in-memory and SQLite stores for the same contract.
