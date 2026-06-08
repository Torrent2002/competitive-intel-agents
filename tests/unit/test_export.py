import json

from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.export import ExportError, ReportExporter, export_run
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AnalysisClaim,
    ReportDraft,
    ReviewFeedback,
    RoundEvent,
    SourceArtifact,
    ToolCall,
)


def _populate_stores(store, journal, run_id="run_001"):
    """Shared fixture: save sources, claims, report, and journal events."""
    store.save_source(
        SourceArtifact(
            id="source_001",
            run_id=run_id,
            url="https://example.com/a",
            title="Source A",
            snippet="Evidence about competitor pricing.",
        )
    )
    store.save_source(
        SourceArtifact(
            id="source_002",
            run_id=run_id,
            url="https://example.com/b",
            title="Source B",
            snippet="Evidence about market share.",
        )
    )
    store.save_claim(
        AnalysisClaim(
            id="claim_001",
            run_id=run_id,
            text="Competitor X lowered prices by 15% in Q1 2026.",
            source_ids=["source_001"],
            confidence="high",
            reasoning="Direct pricing page comparison.",
        )
    )
    store.save_report(
        ReportDraft(
            id="report_001",
            run_id=run_id,
            sections={
                "Overview": "Competitor X is aggressively cutting prices.",
                "Pricing Analysis": "15% price reduction observed.",
            },
            claim_ids=["claim_001"],
            source_ids=["source_001", "source_002"],
        )
    )
    journal.append(
        RoundEvent(
            id="run_001:collector:1",
            run_id=run_id,
            agent="collector",
            round=1,
            decision="continue",
            tool_calls=[
                ToolCall(id="tc_001", name="web_search", args={"q": "pricing"})
            ],
            signals=[],
            review_feedback=[],
            output_artifact_ids=["source_001", "source_002"],
        )
    )
    journal.append(
        RoundEvent(
            id="run_001:analyst:1",
            run_id=run_id,
            agent="analyst",
            round=1,
            decision="continue",
            signals=[],
            output_artifact_ids=["claim_001"],
        )
    )
    journal.append(
        RoundEvent(
            id="run_001:reviewer:1",
            run_id=run_id,
            agent="reviewer",
            round=1,
            decision="stop",
            signals=[],
            review_feedback=[
                ReviewFeedback(
                    issue="weak_inference",
                    target_agent="analyst",
                    target_artifact_id="claim_001",
                    message="Confidence not well supported.",
                    required_action="add_evidence",
                )
            ],
        )
    )


def test_markdown_includes_report_sections():
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    _populate_stores(store, journal)
    exporter = ReportExporter(store, journal, "run_001")

    output = exporter.export_markdown()

    assert "# Competitive Intelligence Report" in output
    assert "## Overview" in output
    assert "## Pricing Analysis" in output
    assert "15% price reduction observed" in output
    assert "`run_001`" in output


def test_markdown_includes_source_and_claim_ids():
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    _populate_stores(store, journal)
    exporter = ReportExporter(store, journal, "run_001")

    output = exporter.export_markdown()

    assert "`source_001`" in output
    assert "`source_002`" in output
    assert "`claim_001`" in output
    assert "Source A" in output
    assert "Source B" in output


def test_markdown_includes_reviewer_feedback():
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    _populate_stores(store, journal)
    exporter = ReportExporter(store, journal, "run_001")

    output = exporter.export_markdown()

    assert "## Reviewer Feedback" in output
    assert "weak_inference" in output


def test_markdown_includes_provenance_appendix():
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    _populate_stores(store, journal)
    exporter = ReportExporter(store, journal, "run_001")

    output = exporter.export_markdown()

    assert "## Provenance Appendix" in output
    assert "Nodes:" in output
    assert "Edges:" in output


def test_json_includes_all_artifacts():
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    _populate_stores(store, journal)
    exporter = ReportExporter(store, journal, "run_001")

    output = exporter.export_json()
    payload = json.loads(output)

    assert payload["run_id"] == "run_001"
    assert payload["report_id"] == "report_001"
    assert len(payload["sources"]) == 2
    assert len(payload["claims"]) == 1
    assert len(payload["review_feedback"]) == 1
    assert "provenance" in payload
    assert payload["provenance"]["run_id"] == "run_001"


def test_html_renders_without_error():
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    _populate_stores(store, journal)
    exporter = ReportExporter(store, journal, "run_001")

    output = exporter.export_html()

    assert "<!DOCTYPE html>" in output
    assert "<title>Competitive Intelligence Report</title>" in output
    assert "Source A" in output
    assert "claim_001" in output


def test_export_fails_for_missing_report():
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    journal.append(
        RoundEvent(
            id="run_x:collector:1",
            run_id="run_x",
            agent="collector",
            round=1,
            decision="continue",
        )
    )

    try:
        ReportExporter(store, journal, "run_x")
        assert False, "expected ExportError"
    except ExportError as exc:
        assert "no report" in str(exc)


def test_export_fails_for_missing_journal_events():
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    store.save_report(
        ReportDraft(
            id="report_y",
            run_id="run_y",
            sections={"Overview": "test"},
            claim_ids=[],
            source_ids=[],
        )
    )

    try:
        ReportExporter(store, journal, "run_y")
        assert False, "expected ExportError"
    except ExportError as exc:
        assert "no journal events" in str(exc)


def test_convenience_export_run_markdown():
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    _populate_stores(store, journal)

    output = export_run(store, journal, "run_001", "markdown")
    assert "# Competitive Intelligence Report" in output


def test_convenience_export_run_json():
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    _populate_stores(store, journal)

    output = export_run(store, journal, "run_001", "json")
    payload = json.loads(output)
    assert payload["run_id"] == "run_001"


def test_convenience_export_run_html():
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    _populate_stores(store, journal)

    output = export_run(store, journal, "run_001", "html")
    assert "<!DOCTYPE html>" in output


def test_export_run_rejects_unsupported_format():
    store = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    _populate_stores(store, journal)

    try:
        export_run(store, journal, "run_001", "pdf")
        assert False, "expected ExportError"
    except ExportError as exc:
        assert "unsupported format" in str(exc)
