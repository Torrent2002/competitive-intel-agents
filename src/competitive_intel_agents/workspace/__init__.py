"""Local persistent workspace for CLI runs."""

from __future__ import annotations

import json
from pathlib import Path

from competitive_intel_agents.artifacts import SQLiteArtifactStore
from competitive_intel_agents.journal import SQLiteJournalStore
from competitive_intel_agents.models import RunResult


class LocalWorkspace:
    """File-backed local workspace for run metadata, artifacts, and journal."""

    def __init__(self, path: str | Path = ".competitive-intel") -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.artifacts = SQLiteArtifactStore(self.path / "artifacts.sqlite")
        self.journal = SQLiteJournalStore(self.path / "journal.sqlite")
        self._runs_path = self.path / "runs.json"
        if not self._runs_path.exists():
            self._runs_path.write_text("[]\n", encoding="utf-8")

    def save_run_result(self, result: RunResult) -> None:
        results = [
            existing
            for existing in self.list_run_results()
            if existing.run_id != result.run_id
        ]
        results.append(result)
        payload = [item.to_dict() for item in results]
        self._runs_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def get_run_result(self, run_id: str) -> RunResult | None:
        for result in self.list_run_results():
            if result.run_id == run_id:
                return result
        return None

    def list_run_results(self) -> list[RunResult]:
        payload = json.loads(self._runs_path.read_text(encoding="utf-8"))
        return [
            RunResult.from_dict(item)
            for item in payload
            if isinstance(item, dict)
        ]


__all__ = ["LocalWorkspace"]
