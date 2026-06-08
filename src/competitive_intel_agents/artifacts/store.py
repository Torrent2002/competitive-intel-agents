"""Artifact store — structured shared memory between agents."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from competitive_intel_agents.models import (
    AnalysisClaim,
    ArtifactStatus,
    ReportDraft,
    SourceArtifact,
)


class ArtifactNotFoundError(ValueError):
    """Raised when referencing an artifact that does not exist."""


class DuplicateArtifactError(ValueError):
    """Raised when saving an artifact id that already exists."""


class InvalidArtifactLineageError(ValueError):
    """Raised when an artifact replacement breaks version lineage rules."""


class ArtifactStore(Protocol):
    """Storage contract for structured agent-to-agent communication."""

    def save_source(self, artifact: SourceArtifact) -> None:
        ...

    def list_sources(
        self, run_id: str, status: ArtifactStatus | None = "active"
    ) -> list[SourceArtifact]:
        ...

    def get_artifact(
        self, artifact_id: str
    ) -> SourceArtifact | AnalysisClaim | ReportDraft:
        ...

    def save_claim(self, claim: AnalysisClaim) -> None:
        ...

    def list_claims(
        self, run_id: str, status: ArtifactStatus | None = "active"
    ) -> list[AnalysisClaim]:
        ...

    def save_report(self, report: ReportDraft) -> None:
        ...

    def get_latest_report(self, run_id: str) -> ReportDraft | None:
        ...

    def list_reports(
        self, run_id: str, status: ArtifactStatus | None = "active"
    ) -> list[ReportDraft]:
        ...

    def mark_superseded(self, artifact_id: str, replacement_id: str) -> None:
        ...

    def mark_rejected(self, artifact_id: str, reason: str) -> None:
        ...


class InMemoryArtifactStore:
    """In-memory artifact store for tests and local single-run usage."""

    def __init__(self) -> None:
        self._sources: dict[str, SourceArtifact] = {}
        self._claims: dict[str, AnalysisClaim] = {}
        self._reports: dict[str, ReportDraft] = {}
        self._statuses: dict[str, ArtifactStatus] = {}
        self._rejection_reasons: dict[str, str] = {}
        self._run_order: dict[str, list[tuple[str, str]]] = {}  # run_id -> [(artifact_id, type)]

    # --- helpers ---

    def _record(self, run_id: str, artifact_id: str, artifact_type: str) -> None:
        if run_id not in self._run_order:
            self._run_order[run_id] = []
        self._run_order[run_id].append((artifact_id, artifact_type))

    def _artifact_exists(self, artifact_id: str) -> bool:
        return (
            artifact_id in self._sources
            or artifact_id in self._claims
            or artifact_id in self._reports
        )

    def _require_new_artifact(self, artifact_id: str) -> None:
        if self._artifact_exists(artifact_id):
            raise DuplicateArtifactError(f"duplicate artifact id: {artifact_id}")

    def _require_artifact(self, artifact_id: str) -> None:
        if not self._artifact_exists(artifact_id):
            raise ArtifactNotFoundError(
                f"artifact not found: {artifact_id}"
            )

    def _get_artifact(
        self, artifact_id: str
    ) -> tuple[SourceArtifact | AnalysisClaim | ReportDraft, str]:
        if artifact_id in self._sources:
            return self._sources[artifact_id], "source"
        if artifact_id in self._claims:
            return self._claims[artifact_id], "claim"
        if artifact_id in self._reports:
            return self._reports[artifact_id], "report"
        raise ArtifactNotFoundError(f"artifact not found: {artifact_id}")

    def _update_status(self, artifact_id: str, new_status: ArtifactStatus) -> None:
        self._require_artifact(artifact_id)
        self._statuses[artifact_id] = new_status

    def _with_current_status(
        self, artifact: SourceArtifact | AnalysisClaim | ReportDraft
    ):
        return replace(artifact, status=self._statuses.get(artifact.id, artifact.status))

    def _validate_replacement(self, artifact_id: str, replacement_id: str) -> None:
        old, old_type = self._get_artifact(artifact_id)
        replacement_artifact, replacement_type = self._get_artifact(replacement_id)
        if old.run_id != replacement_artifact.run_id:
            raise InvalidArtifactLineageError(
                "replacement artifact must have the same run_id"
            )
        if old_type != replacement_type:
            raise InvalidArtifactLineageError(
                "replacement artifact must have the same artifact type"
            )
        if replacement_artifact.supersedes_id != artifact_id:
            raise InvalidArtifactLineageError(
                "replacement artifact supersedes_id must point to the old artifact"
            )
        if replacement_artifact.version <= old.version:
            raise InvalidArtifactLineageError(
                "replacement artifact version must be greater than old artifact version"
            )

    # --- source artifacts ---

    def save_source(self, artifact: SourceArtifact) -> None:
        self._require_new_artifact(artifact.id)
        self._sources[artifact.id] = artifact
        self._statuses[artifact.id] = artifact.status
        self._record(artifact.run_id, artifact.id, "source")

    def list_sources(
        self, run_id: str, status: ArtifactStatus | None = "active"
    ) -> list[SourceArtifact]:
        if run_id not in self._run_order:
            return []
        return [
            self._with_current_status(self._sources[aid])
            for aid, atype in self._run_order[run_id]
            if atype == "source" and aid in self._sources
            and (status is None or self._statuses.get(aid, "active") == status)
        ]

    def get_artifact(
        self, artifact_id: str
    ) -> SourceArtifact | AnalysisClaim | ReportDraft:
        artifact, _ = self._get_artifact(artifact_id)
        return self._with_current_status(artifact)

    # --- claims ---

    def save_claim(self, claim: AnalysisClaim) -> None:
        self._require_new_artifact(claim.id)
        self._claims[claim.id] = claim
        self._statuses[claim.id] = claim.status
        self._record(claim.run_id, claim.id, "claim")

    def list_claims(
        self, run_id: str, status: ArtifactStatus | None = "active"
    ) -> list[AnalysisClaim]:
        if run_id not in self._run_order:
            return []
        return [
            self._with_current_status(self._claims[aid])
            for aid, atype in self._run_order[run_id]
            if atype == "claim" and aid in self._claims
            and (status is None or self._statuses.get(aid, "active") == status)
        ]

    # --- reports ---

    def save_report(self, report: ReportDraft) -> None:
        self._require_new_artifact(report.id)
        self._reports[report.id] = report
        self._statuses[report.id] = report.status
        self._record(report.run_id, report.id, "report")

    def get_latest_report(self, run_id: str) -> ReportDraft | None:
        reports = self.list_reports(run_id)
        if not reports:
            return None
        return max(reports, key=lambda r: r.version)

    def list_reports(
        self, run_id: str, status: ArtifactStatus | None = "active"
    ) -> list[ReportDraft]:
        if run_id not in self._run_order:
            return []
        return [
            self._with_current_status(self._reports[aid])
            for aid, atype in self._run_order[run_id]
            if atype == "report" and aid in self._reports
            and (status is None or self._statuses.get(aid, "active") == status)
        ]

    # --- status mutations ---

    def mark_superseded(self, artifact_id: str, replacement_id: str) -> None:
        self._validate_replacement(artifact_id, replacement_id)
        self._update_status(artifact_id, "superseded")

    def mark_rejected(self, artifact_id: str, reason: str) -> None:
        self._update_status(artifact_id, "rejected")
        self._rejection_reasons[artifact_id] = reason


class SQLiteArtifactStore:
    """SQLite-backed artifact store for persistence across runs."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                version INTEGER NOT NULL DEFAULT 1,
                supersedes_id TEXT,
                payload TEXT NOT NULL,
                rejection_reason TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    # --- helpers ---

    def _insert_artifact(
        self,
        artifact: SourceArtifact | AnalysisClaim | ReportDraft,
        artifact_type: str,
    ) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO artifacts
                    (id, run_id, type, status, version, supersedes_id, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    artifact.run_id,
                    artifact_type,
                    artifact.status,
                    artifact.version,
                    artifact.supersedes_id,
                    json.dumps(artifact.to_dict(), sort_keys=True),
                    getattr(artifact, "retrieved_at", None)
                    or getattr(artifact, "created_at", None)
                    or "",
                ),
            )
            self._connection.commit()
        except sqlite3.IntegrityError as error:
            raise DuplicateArtifactError(
                f"duplicate artifact id: {artifact.id}"
            ) from error

    def _list_by_type(
        self,
        run_id: str,
        artifact_type: str,
        model_class: type,
        status: ArtifactStatus | None = None,
    ) -> list:
        if status is None:
            rows = self._connection.execute(
                """
                SELECT payload, status FROM artifacts
                WHERE run_id = ? AND type = ?
                ORDER BY rowid ASC
                """,
                (run_id, artifact_type),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT payload, status FROM artifacts
                WHERE run_id = ? AND type = ? AND status = ?
                ORDER BY rowid ASC
                """,
                (run_id, artifact_type, status),
            ).fetchall()
        return [
            replace(model_class.from_dict(json.loads(row[0])), status=row[1])
            for row in rows
        ]

    def _require_artifact(self, artifact_id: str) -> None:
        row = self._connection.execute(
            "SELECT 1 FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise ArtifactNotFoundError(
                f"artifact not found: {artifact_id}"
            )

    def _get_artifact(
        self, artifact_id: str
    ) -> tuple[SourceArtifact | AnalysisClaim | ReportDraft, str]:
        row = self._connection.execute(
            """
            SELECT payload, type, status FROM artifacts
            WHERE id = ?
            """,
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise ArtifactNotFoundError(f"artifact not found: {artifact_id}")
        model_class = {
            "source": SourceArtifact,
            "claim": AnalysisClaim,
            "report": ReportDraft,
        }[row[1]]
        artifact = replace(model_class.from_dict(json.loads(row[0])), status=row[2])
        return artifact, row[1]

    def _validate_replacement(self, artifact_id: str, replacement_id: str) -> None:
        old, old_type = self._get_artifact(artifact_id)
        replacement_artifact, replacement_type = self._get_artifact(replacement_id)
        if old.run_id != replacement_artifact.run_id:
            raise InvalidArtifactLineageError(
                "replacement artifact must have the same run_id"
            )
        if old_type != replacement_type:
            raise InvalidArtifactLineageError(
                "replacement artifact must have the same artifact type"
            )
        if replacement_artifact.supersedes_id != artifact_id:
            raise InvalidArtifactLineageError(
                "replacement artifact supersedes_id must point to the old artifact"
            )
        if replacement_artifact.version <= old.version:
            raise InvalidArtifactLineageError(
                "replacement artifact version must be greater than old artifact version"
            )

    def _update_status(
        self, artifact_id: str, new_status: ArtifactStatus, reason: str | None = None
    ) -> None:
        self._require_artifact(artifact_id)
        if reason is not None:
            self._connection.execute(
                """
                UPDATE artifacts SET status = ?, rejection_reason = ? WHERE id = ?
                """,
                (new_status, reason, artifact_id),
            )
        else:
            self._connection.execute(
                "UPDATE artifacts SET status = ? WHERE id = ?",
                (new_status, artifact_id),
            )
        self._connection.commit()

    # --- source artifacts ---

    def save_source(self, artifact: SourceArtifact) -> None:
        self._insert_artifact(artifact, "source")

    def list_sources(
        self, run_id: str, status: ArtifactStatus | None = "active"
    ) -> list[SourceArtifact]:
        return self._list_by_type(run_id, "source", SourceArtifact, status)

    def get_artifact(
        self, artifact_id: str
    ) -> SourceArtifact | AnalysisClaim | ReportDraft:
        artifact, _ = self._get_artifact(artifact_id)
        return artifact

    # --- claims ---

    def save_claim(self, claim: AnalysisClaim) -> None:
        self._insert_artifact(claim, "claim")

    def list_claims(
        self, run_id: str, status: ArtifactStatus | None = "active"
    ) -> list[AnalysisClaim]:
        return self._list_by_type(run_id, "claim", AnalysisClaim, status)

    # --- reports ---

    def save_report(self, report: ReportDraft) -> None:
        self._insert_artifact(report, "report")

    def get_latest_report(self, run_id: str) -> ReportDraft | None:
        reports = self.list_reports(run_id)
        if not reports:
            return None
        return max(reports, key=lambda r: r.version)

    def list_reports(
        self, run_id: str, status: ArtifactStatus | None = "active"
    ) -> list[ReportDraft]:
        return self._list_by_type(run_id, "report", ReportDraft, status)

    # --- status mutations ---

    def mark_superseded(self, artifact_id: str, replacement_id: str) -> None:
        self._validate_replacement(artifact_id, replacement_id)
        self._update_status(artifact_id, "superseded")

    def mark_rejected(self, artifact_id: str, reason: str) -> None:
        self._update_status(artifact_id, "rejected", reason)
