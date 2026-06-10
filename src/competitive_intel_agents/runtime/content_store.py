"""Local persistence for large information-acquisition payloads."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol


CONTENT_FIELDS = ("content", "text", "html", "raw_content")


class ContentTool(Protocol):
    name: str

    def run(self, args: dict) -> dict:
        ...


class LocalContentStore:
    """Persist cleaned full text so tool results can return compact references."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save_text(
        self,
        text: str,
        *,
        source_id: str,
        suffix: str = ".txt",
    ) -> dict:
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        safe_source = _safe_filename(source_id) or "content"
        path = self.root / f"{safe_source}-{content_hash[:16]}{suffix}"
        path.write_text(text, encoding="utf-8")
        return {
            "content_ref": f"file:{path}",
            "content_hash": content_hash,
            "char_count": len(text),
        }


class PersistedContentTool:
    """Wrap any content-producing tool and replace large text with a reference."""

    def __init__(
        self,
        tool: ContentTool,
        content_store: LocalContentStore,
        summary_chars: int = 1000,
        preview_chars: int = 300,
    ) -> None:
        self.name = tool.name
        self._tool = tool
        self._content_store = content_store
        self._summary_chars = summary_chars
        self._preview_chars = preview_chars

    def run(self, args: dict) -> dict:
        return self.persist_payload(self._tool.run(args))

    def persist_payload(self, payload: dict) -> dict:
        payload = dict(payload)
        field = next(
            (
                key
                for key in CONTENT_FIELDS
                if isinstance(payload.get(key), str) and payload.get(key)
            ),
            None,
        )
        if field is None:
            return payload

        full_text = str(payload[field])
        source_id = str(payload.get("url") or payload.get("id") or self.name)
        persisted = self._content_store.save_text(full_text, source_id=source_id)
        summary = str(payload.get("summary") or full_text[: self._summary_chars])
        preview = str(payload.get("preview") or full_text[: self._preview_chars])
        payload.update(persisted)
        payload["summary"] = summary
        payload["preview"] = preview
        payload[field] = summary
        payload["content_field"] = field
        return payload


def _safe_filename(value: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in value
    ).strip("._")
