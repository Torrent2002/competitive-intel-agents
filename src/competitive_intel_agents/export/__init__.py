"""Report export: produce polished report bundles for review and sharing."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from competitive_intel_agents.artifacts import ArtifactStore
from competitive_intel_agents.journal import JournalStore
from competitive_intel_agents.models import ReportDraft, RunResult
from competitive_intel_agents.provenance import (
    build_provenance_graph,
    render_provenance_appendix,
)


class ExportError(ValueError):
    """Raised when export cannot proceed (missing run, missing report, etc)."""


class ReportExporter:
    """Read stores and produce a report bundle in markdown, json, or html."""

    def __init__(
        self,
        artifacts: ArtifactStore,
        journal: JournalStore,
        run_id: str,
    ) -> None:
        self._artifacts = artifacts
        self._journal = journal
        self._run_id = run_id

        self._report = artifacts.get_latest_report(run_id)
        if self._report is None:
            raise ExportError(f"no report found for run: {run_id}")

        self._sources = artifacts.list_sources(run_id)
        self._claims = artifacts.list_claims(run_id)
        events = journal.list_run_events(run_id)
        if not events:
            raise ExportError(f"no journal events found for run: {run_id}")

        self._feedback = [
            item for event in events for item in event.review_feedback
        ]
        self._provenance = build_provenance_graph(
            journal, artifacts, run_id, self._report.id
        )

    @property
    def report(self) -> ReportDraft:
        return self._report

    def export_markdown(self) -> str:
        """Render a self-contained markdown report with appendices."""
        lines = [
            "# Competitive Intelligence Report",
            "",
            f"**Run:** `{self._run_id}`",
            f"**Report:** `{self._report.id}`",
            f"**Sources:** {len(self._sources)}",
            f"**Claims:** {len(self._claims)}",
            "",
            "---",
            "",
        ]

        for section, content in self._report.sections.items():
            lines.extend([f"## {section}", "", content.strip(), ""])

        lines.extend([
            "---",
            "",
            "## Evidence Index",
            "",
        ])
        for claim in self._claims:
            lines.append(f"- **{claim.id}**: {claim.text}")
            for source_id in claim.source_ids:
                source = self._find_source(source_id)
                label = source.title if source else source_id
                lines.append(f"  - ← `{source_id}` ({label})")

        lines.extend(["", "## Sources", ""])
        for source in self._sources:
            lines.append(f"- [{source.title}]({source.url}) — `{source.id}`")

        if self._feedback:
            lines.extend(["", "## Reviewer Feedback", ""])
            for item in self._feedback:
                lines.append(
                    f"- **{item.issue}** → `{item.target_agent}` "
                    f"(artifact `{item.target_artifact_id}`): {item.message}"
                )

        lines.extend(["", render_provenance_appendix(self._provenance)])
        return "\n".join(lines) + "\n"

    def export_json(self) -> str:
        """Export all artifacts, events, and provenance as a JSON bundle."""
        payload = {
            "run_id": self._run_id,
            "report_id": self._report.id,
            "report": self._report.to_dict(),
            "sources": [source.to_dict() for source in self._sources],
            "claims": [claim.to_dict() for claim in self._claims],
            "review_feedback": [
                item.to_dict() for item in self._feedback
            ],
            "provenance": self._provenance.to_dict(),
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    def export_html(self) -> str:
        """Render a self-contained HTML report page."""
        sections_html = ""
        for section, content in self._report.sections.items():
            sections_html += (
                f"<section><h2>{_esc(section)}</h2>"
                f"<div>{_esc(content)}</div></section>\n"
            )

        sources_html = ""
        for source in self._sources:
            sources_html += (
                f'<li><a href="{_esc(source.url)}">{_esc(source.title)}</a>'
                f" <code>{_esc(source.id)}</code></li>\n"
            )

        claims_html = ""
        for claim in self._claims:
            claims_html += f"<li><strong>{_esc(claim.id)}</strong>: {_esc(claim.text)}"
            source_ids = ", ".join(claim.source_ids)
            claims_html += f" <em>(sources: {_esc(source_ids)})</em></li>\n"

        feedback_html = ""
        if self._feedback:
            items = ""
            for item in self._feedback:
                items += (
                    f"<li><strong>{_esc(item.issue)}</strong> → "
                    f"{_esc(item.target_agent)} "
                    f"(<code>{_esc(item.target_artifact_id)}</code>): "
                    f"{_esc(item.message)}</li>\n"
                )
            feedback_html = f"<section><h2>Reviewer Feedback</h2><ul>{items}</ul></section>"

        provenance_html = ""
        if self._provenance.edges:
            edges_list = ""
            for edge in self._provenance.edges:
                edges_list += (
                    f"<li><code>{_esc(edge.source_id)}</code> "
                    f"--{_esc(edge.relation)}--&gt; "
                    f"<code>{_esc(edge.target_id)}</code></li>\n"
                )
            provenance_html = (
                "<section><h2>Provenance</h2>"
                f"<p>Nodes: {len(self._provenance.nodes)}, "
                f"Edges: {len(self._provenance.edges)}</p>"
                f"<ul>{edges_list}</ul></section>"
            )

        return (
            "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<title>Competitive Intelligence Report</title>\n"
            "<style>\n"
            "body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;"
            "max-width:900px;margin:0 auto;padding:2rem;line-height:1.6;"
            "color:#1a1a1a;}\n"
            "h1{border-bottom:2px solid #2563eb;padding-bottom:.5rem;}\n"
            "h2{margin-top:2rem;color:#2563eb;}\n"
            "code{background:#f3f4f6;padding:.1em .3em;border-radius:3px;"
            "font-size:.9em;}\n"
            "section{margin-bottom:2rem;}\n"
            "ul{list-style:disc;padding-left:1.5rem;}\n"
            ".meta{color:#6b7280;font-size:.9em;}\n"
            "</style>\n</head>\n<body>\n"
            f"<h1>Competitive Intelligence Report</h1>\n"
            f'<p class="meta">Run: <code>{_esc(self._run_id)}</code> | '
            f"Report: <code>{_esc(self._report.id)}</code> | "
            f"Sources: {len(self._sources)} | "
            f"Claims: {len(self._claims)}</p>\n"
            f"{sections_html}"
            f"<section><h2>Sources</h2><ul>{sources_html}</ul></section>\n"
            f"<section><h2>Claims</h2><ul>{claims_html}</ul></section>\n"
            f"{feedback_html}"
            f"{provenance_html}"
            "\n</body>\n</html>\n"
        )

    def _find_source(self, source_id: str):
        for source in self._sources:
            if source.id == source_id:
                return source
        return None


def _esc(text: str) -> str:
    """Minimal HTML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def export_run(
    artifacts: ArtifactStore,
    journal: JournalStore,
    run_id: str,
    fmt: str = "markdown",
) -> str:
    """Convenience function: export a run to the given format string."""
    exporter = ReportExporter(artifacts, journal, run_id)
    if fmt == "markdown":
        return exporter.export_markdown()
    if fmt == "json":
        return exporter.export_json()
    if fmt == "html":
        return exporter.export_html()
    raise ExportError(f"unsupported format: {fmt}")


__all__ = [
    "ExportError",
    "ReportExporter",
    "export_run",
]
