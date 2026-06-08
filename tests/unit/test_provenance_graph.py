from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.journal import InMemoryJournalStore
from competitive_intel_agents.models import (
    AnalysisClaim,
    ReportDraft,
    RoundEvent,
    SourceArtifact,
    ToolCall,
)
from competitive_intel_agents.provenance import (
    build_provenance_graph,
    render_provenance_appendix,
)


def test_provenance_graph_links_report_claim_source_and_collector_event() -> None:
    artifacts = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    artifacts.save_source(
        SourceArtifact(
            id="source_001",
            run_id="run_001",
            url="https://example.com",
            title="Example",
        )
    )
    artifacts.save_claim(
        AnalysisClaim(
            id="claim_001",
            run_id="run_001",
            text="ACME has evidence.",
            source_ids=["source_001"],
        )
    )
    artifacts.save_report(
        ReportDraft(
            id="report_001",
            run_id="run_001",
            sections={"Overview": "Summary", "Sources": "- source_001"},
            claim_ids=["claim_001"],
            source_ids=["source_001"],
        )
    )
    journal.append(
        RoundEvent(
            id="run_001:collector:2",
            run_id="run_001",
            agent="collector",
            round=2,
            decision="stop",
            tool_calls=[
                ToolCall(
                    id="fetch_001",
                    name="web_fetch",
                    args={"url": "https://example.com"},
                    requested_by="collector",
                )
            ],
            output_artifact_ids=["source_001"],
        )
    )

    graph = build_provenance_graph(journal, artifacts, "run_001")

    assert graph.report_id == "report_001"
    assert graph.nodes["report_001"].kind == "report"
    assert graph.nodes["claim_001"].kind == "claim"
    assert graph.nodes["source_001"].kind == "source"
    assert graph.nodes["run_001:collector:2"].kind == "event"
    assert graph.nodes["fetch_001"].kind == "tool_call"
    assert ("report_001", "claim_001", "uses_claim") in graph.edge_tuples()
    assert ("claim_001", "source_001", "supported_by") in graph.edge_tuples()
    assert ("source_001", "run_001:collector:2", "produced_by") in graph.edge_tuples()
    assert ("run_001:collector:2", "fetch_001", "executed_tool") in graph.edge_tuples()


def test_provenance_appendix_reports_missing_links() -> None:
    artifacts = InMemoryArtifactStore()
    journal = InMemoryJournalStore()
    artifacts.save_report(
        ReportDraft(
            id="report_001",
            run_id="run_001",
            sections={"Overview": "Summary"},
            claim_ids=["claim_missing"],
            source_ids=["source_missing"],
        )
    )

    graph = build_provenance_graph(journal, artifacts, "run_001")
    appendix = render_provenance_appendix(graph)

    assert "Missing provenance" in appendix
    assert "claim_missing" in appendix
    assert "source_missing" in appendix
