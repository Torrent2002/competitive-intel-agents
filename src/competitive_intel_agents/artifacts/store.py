"""Artifact store — structured shared memory between agents."""

from __future__ import annotations

import json
import sqlite3
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


class ArtifactStore(Protocol):
    """Storage contract for structured agent-to-agent communication."""

    def save_source(self, artifact: SourceArtifact) -> None:
        ...

    def list_sources(self, run_id: str) -> list[SourceArtifact]:
        ...

    def save_claim(self, claim: AnalysisClaim) -> None:
        ...

    def list_claims(
        self, run_id: str, status: ArtifactStatus = "active"
    ) -> list[AnalysisClaim]:
        ...

    def save_report(self, report: ReportDraft) -> None:
        ...

    def get_latest_report(self, run_id: str) -> ReportDraft | None:
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

    def _require_artifact(self, artifact_id: str) -> None:
        found = (
            artifact_id in self._sources
            or artifact_id in self._claims
            or artifact_id in self._reports
        )
        if not found:
            raise ArtifactNotFoundError(
                f"artifact not found: {artifact_id}"
            )

    def _update_status(self, artifact_id: str, new_status: ArtifactStatus) -> None:
        self._require_artifact(artifact_id)
        self._statuses[artifact_id] = new_status

    # --- source artifacts ---

    def save_source(self, artifact: SourceArtifact) -> None:
        self._sources[artifact.id] = artifact
        self._statuses[artifact.id] = artifact.status
        self._record(artifact.run_id, artifact.id, "source")

    def list_sources(self, run_id: str) -> list[SourceArtifact]:
        if run_id not in self._run_order:
            return []
        return [
            self._sources[aid]
            for aid, atype in self._run_order[run_id]
            if atype == "source" and aid in self._sources
            and self._statuses.get(aid, "active") == "active"
        ]

    # --- claims ---

    def save_claim(self, claim: AnalysisClaim) -> None:
        self._claims[claim.id] = claim
        self._statuses[claim.id] = claim.status
        self._record(claim.run_id, claim.id, "claim")

    def list_claims(
        self, run_id: str, status: ArtifactStatus = "active"
    ) -> list[AnalysisClaim]:
        if run_id not in self._run_order:
            return []
        return [
            self._claims[aid]
            for aid, atype in self._run_order[run_id]
            if atype == "claim" and aid in self._claims
            and self._statuses.get(aid, "active") == status
        ]

    # --- reports ---

    def save_report(self, report: ReportDraft) -> None:
        self._reports[report.id] = report
        self._statuses[report.id] = report.status
        self._record(report.run_id, report.id, "report")

    def get_latest_report(self, run_id: str) -> ReportDraft | None:
        if run_id not in self._run_order:
            return None
        reports = [
            self._reports[aid]
            for aid, atype in self._run_order[run_id]
            if atype == "report" and aid in self._reports
            and self._statuses.get(aid, "active") == "active"
        ]
        if not reports:
            return None
        return max(reports, key=lambda r: r.version)

    # --- status mutations ---

    def mark_superseded(self, artifact_id: str, replacement_id: str) -> None:
        self._require_artifact(replacement_id)  # new version must already be saved
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
        self._connection.execute(
            """
            INSERT OR REPLACE INTO artifacts
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
                SELECT payload FROM artifacts
                WHERE run_id = ? AND type = ?
                ORDER BY rowid ASC
                """,
                (run_id, artifact_type),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT payload FROM artifacts
                WHERE run_id = ? AND type = ? AND status = ?
                ORDER BY rowid ASC
                """,
                (run_id, artifact_type, status),
            ).fetchall()
        return [model_class.from_dict(json.loads(row[0])) for row in rows]

    def _require_artifact(self, artifact_id: str) -> None:
        row = self._connection.execute(
            "SELECT 1 FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise ArtifactNotFoundError(
                f"artifact not found: {artifact_id}"
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

    def list_sources(self, run_id: str) -> list[SourceArtifact]:
        return self._list_by_type(run_id, "source", SourceArtifact, "active")

    # --- claims ---

    def save_claim(self, claim: AnalysisClaim) -> None:
        self._insert_artifact(claim, "claim")

    def list_claims(
        self, run_id: str, status: ArtifactStatus = "active"
    ) -> list[AnalysisClaim]:
        return self._list_by_type(run_id, "claim", AnalysisClaim, status)

    # --- reports ---

    def save_report(self, report: ReportDraft) -> None:
        self._insert_artifact(report, "report")

    def get_latest_report(self, run_id: str) -> ReportDraft | None:
        rows = self._connection.execute(
            """
            SELECT payload FROM artifacts
            WHERE run_id = ? AND type = 'report' AND status = 'active'
            ORDER BY version DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchall()
        if not rows:
            return None
        return ReportDraft.from_dict(json.loads(rows[0][0]))

    # --- status mutations ---

    def mark_superseded(self, artifact_id: str, replacement_id: str) -> None:
        self._require_artifact(replacement_id)
        self._update_status(artifact_id, "superseded")

    def mark_rejected(self, artifact_id: str, reason: str) -> None:
        self._update_status(artifact_id, "rejected", reason)
