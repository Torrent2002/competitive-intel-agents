"""Causal provenance graph export for report evidence chains."""

from __future__ import annotations

from dataclasses import dataclass, field

from competitive_intel_agents.artifacts import ArtifactNotFoundError, ArtifactStore
from competitive_intel_agents.journal import JournalStore


@dataclass(frozen=True)
class ProvenanceNode:
    id: str
    kind: str
    label: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProvenanceEdge:
    source_id: str
    target_id: str
    relation: str


@dataclass(frozen=True)
class ProvenanceGraph:
    run_id: str
    report_id: str | None
    nodes: dict[str, ProvenanceNode]
    edges: list[ProvenanceEdge]
    missing: list[str] = field(default_factory=list)

    def edge_tuples(self) -> set[tuple[str, str, str]]:
        return {
            (edge.source_id, edge.target_id, edge.relation)
            for edge in self.edges
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "report_id": self.report_id,
            "nodes": {
                node_id: {
                    "kind": node.kind,
                    "label": node.label,
                    "metadata": node.metadata,
                }
                for node_id, node in self.nodes.items()
            },
            "edges": [
                {
                    "source_id": edge.source_id,
                    "target_id": edge.target_id,
                    "relation": edge.relation,
                }
                for edge in self.edges
            ],
            "missing": list(self.missing),
        }


def build_provenance_graph(
    journal: JournalStore,
    artifacts: ArtifactStore,
    run_id: str,
    report_id: str | None = None,
) -> ProvenanceGraph:
    """Build a report-centered graph from stores without mutating run state."""

    report = (
        artifacts.get_artifact(report_id)
        if report_id is not None
        else artifacts.get_latest_report(run_id)
    )
    nodes: dict[str, ProvenanceNode] = {}
    edges: list[ProvenanceEdge] = []
    missing: list[str] = []

    events = journal.list_run_events(run_id)
    artifact_event = {
        artifact_id: event
        for event in events
        for artifact_id in event.output_artifact_ids
    }
    for event in events:
        _add_node(
            nodes,
            ProvenanceNode(
                id=event.id,
                kind="event",
                label=f"{event.agent} round {event.round}",
                metadata={"decision": event.decision, "signals": event.signals},
            ),
        )
        for call in event.tool_calls:
            _add_node(
                nodes,
                ProvenanceNode(
                    id=call.id,
                    kind="tool_call",
                    label=call.name,
                    metadata={"requested_by": call.requested_by, "args": call.args},
                ),
            )
            edges.append(ProvenanceEdge(event.id, call.id, "executed_tool"))

    if report is None:
        return ProvenanceGraph(run_id, None, nodes, edges, ["report"])

    _add_node(
        nodes,
        ProvenanceNode(
            id=report.id,
            kind="report",
            label=report.id,
            metadata={"sections": list(report.sections)},
        ),
    )
    for claim_id in report.claim_ids:
        try:
            claim = artifacts.get_artifact(claim_id)
        except ArtifactNotFoundError:
            missing.append(claim_id)
            continue
        _add_node(
            nodes,
            ProvenanceNode(
                id=claim.id,
                kind="claim",
                label=getattr(claim, "text", claim.id),
                metadata={"source_ids": getattr(claim, "source_ids", [])},
            ),
        )
        edges.append(ProvenanceEdge(report.id, claim.id, "uses_claim"))
        _link_artifact_event(nodes, edges, artifact_event, claim.id, missing)
        for source_id in claim.source_ids:
            _link_source(nodes, edges, artifacts, artifact_event, claim.id, source_id, missing)

    for source_id in report.source_ids:
        if source_id not in nodes:
            _link_source(nodes, edges, artifacts, artifact_event, report.id, source_id, missing)

    return ProvenanceGraph(run_id, report.id, nodes, edges, _dedupe(missing))


def render_provenance_appendix(graph: ProvenanceGraph) -> str:
    """Render a compact markdown appendix suitable for report export."""

    lines = ["## Provenance Appendix", ""]
    if graph.report_id:
        lines.append(f"- Report: `{graph.report_id}`")
    lines.append(f"- Nodes: {len(graph.nodes)}")
    lines.append(f"- Edges: {len(graph.edges)}")
    if graph.missing:
        lines.extend(["", "### Missing provenance"])
        for item in graph.missing:
            lines.append(f"- `{item}`")
    if graph.edges:
        lines.extend(["", "### Causal links"])
        for edge in graph.edges:
            lines.append(
                f"- `{edge.source_id}` --{edge.relation}--> `{edge.target_id}`"
            )
    return "\n".join(lines)


def _link_source(
    nodes: dict[str, ProvenanceNode],
    edges: list[ProvenanceEdge],
    artifacts: ArtifactStore,
    artifact_event,
    parent_id: str,
    source_id: str,
    missing: list[str],
) -> None:
    try:
        source = artifacts.get_artifact(source_id)
    except ArtifactNotFoundError:
        missing.append(source_id)
        return
    _add_node(
        nodes,
        ProvenanceNode(
            id=source.id,
            kind="source",
            label=getattr(source, "title", source.id),
            metadata={"url": getattr(source, "url", "")},
        ),
    )
    relation = "supported_by" if parent_id.startswith("claim_") else "uses_source"
    edges.append(ProvenanceEdge(parent_id, source.id, relation))
    _link_artifact_event(nodes, edges, artifact_event, source.id, missing)


def _link_artifact_event(
    nodes: dict[str, ProvenanceNode],
    edges: list[ProvenanceEdge],
    artifact_event,
    artifact_id: str,
    missing: list[str],
) -> None:
    event = artifact_event.get(artifact_id)
    if event is None:
        missing.append(f"event_for:{artifact_id}")
        return
    if event.id not in nodes:
        _add_node(
            nodes,
            ProvenanceNode(id=event.id, kind="event", label=f"{event.agent} round {event.round}"),
        )
    edges.append(ProvenanceEdge(artifact_id, event.id, "produced_by"))


def _add_node(nodes: dict[str, ProvenanceNode], node: ProvenanceNode) -> None:
    nodes.setdefault(node.id, node)


def _dedupe(items: list[str]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


__all__ = [
    "ProvenanceEdge",
    "ProvenanceGraph",
    "ProvenanceNode",
    "build_provenance_graph",
    "render_provenance_appendix",
]
