# 24 Full Provenance Graph

## Goal

Expand provenance from source ids to a causal graph linking report sections,
claims, sources, tool calls, and journal events.

## Scope

In scope:

- Causal parent fields for artifacts.
- Mapping source artifacts to tool call events.
- Mapping claims to source artifacts.
- Mapping report sections to claim ids.
- Provenance export for report appendix.
- Golden replay checks for causal-chain completeness.

Out of scope:

- Graph database.
- Visual graph UI.
- Cross-run provenance.

## Tests

- Every source can trace to a collector tool call event.
- Every claim can trace to source artifacts.
- Every report source id exists.
- Exported provenance contains artifact ids and event ids.

## Done Criteria

- A final report can explain not only which source supports a claim, but which
  agent round produced that source.
