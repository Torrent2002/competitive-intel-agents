# V1 Extension Plan

## Why This Plan Exists

Modules 01-17 complete the v0 engineering core: role-bounded agents, structured
artifacts, reviewer feedback, bounded rework primitives, terminal-dashboard
rendering, and golden replay metrics.

That is enough to prove the architecture. It is not yet enough to feel like a
finished product.

README promises a system that is inspectable, replayable, and usable from an
operator-facing interface. The current v0 still has gaps around interaction,
persistence, real collection/model adapters, provenance depth, and demo polish.
This document turns those gaps into the next module sequence.

## Current V0 Reality

Implemented:

- deterministic fake end-to-end pipeline;
- CLI `run` command;
- source, claim, report, reviewer feedback artifacts;
- journal events and runtime harness decisions;
- bounded rework loop primitive;
- terminal dashboard snapshot/rendering module;
- golden replay runner and metrics;
- Chinese `docs/learn` coverage for modules 01-17.

Not yet product-complete:

- no interactive CLI conversation with agents;
- dashboard rendering is not exposed as a user-facing command;
- no persistent run database wired into CLI by default;
- web tools are fake, not real search/fetch adapters;
- model runtime is fake-first and not connected to provider config;
- agents use deterministic rules, not provider-backed structured generation;
- provenance is source-id level, not full causal-chain replay;
- rework loop is implemented but not integrated into normal orchestrator run mode;
- no basic web UI;
- no packaged demo workflow or operator guide.

## V1 Module Sequence

| Order | Module | Purpose |
|---|---|---|
| 18 | Interactive CLI Session | Let a user run and inspect the system conversationally in the terminal. |
| 19 | Dashboard CLI Command | Expose per-run dashboard output through CLI commands. |
| 20 | Persistent Local Workspace | Save runs, journal, artifacts, reports, and dashboard state across processes. |
| 21 | Real Web Collection Tools | Replace fake search/fetch with real, policy-bounded adapters. |
| 22 | Provider-Backed Model Runtime | Add configurable LLM providers while preserving fake mode. |
| 23 | Structured Agent Prompts | Move deterministic agents toward schema-constrained model-backed behavior. |
| 24 | Full Provenance Graph | Trace report claims back through claims, sources, tool calls, and journal events. |
| 25 | Reliability Harness v1 | Add stall detection, retry policy, recovery, and richer health signals. |
| 26 | Integrated Rework Orchestration | Make rework part of normal run execution, not only a standalone primitive. |
| 27 | Basic Web Dashboard | Provide a browser UI for run status, artifacts, report, and feedback. |
| 28 | Report Export Package | Produce a user-facing report bundle with markdown, JSON, and traceability appendix. |
| 29 | Golden Suite Expansion and CI | Broaden golden cases and make replay suitable for CI gates. |
| 30 | Demo and Operator Polish | Make the project interview-ready and handoff-ready. |

## Milestones

### Milestone 5: Usable Local Operator Experience

Modules:

- 18 Interactive CLI Session
- 19 Dashboard CLI Command
- 20 Persistent Local Workspace

Done when:

- a user can start a terminal session, enter a company and competitors, run the
  pipeline, inspect dashboard/report/sources/claims, and save outputs;
- run state survives process exit;
- README commands match actual behavior.

### Milestone 6: Real Collection and Model Integration

Modules:

- 21 Real Web Collection Tools
- 22 Provider-Backed Model Runtime
- 23 Structured Agent Prompts

Done when:

- fake mode remains deterministic for tests;
- local mode can call real search/fetch adapters;
- provider-backed agents emit structured artifacts validated by the same models.

### Milestone 7: Production-Grade Audit and Recovery

Modules:

- 24 Full Provenance Graph
- 25 Reliability Harness v1
- 26 Integrated Rework Orchestration

Done when:

- every report claim can be traced to source artifacts and creating journal events;
- stalled or repeated runs produce actionable diagnostics;
- reviewer feedback can drive bounded automatic repair inside a normal run.

### Milestone 8: Product Surface and Regression Confidence

Modules:

- 27 Basic Web Dashboard
- 28 Report Export Package
- 29 Golden Suite Expansion and CI
- 30 Demo and Operator Polish

Done when:

- the project has a credible visual/operator-facing surface;
- exported reports explain their evidence;
- golden replay catches regressions in CI;
- a reviewer/interviewer can understand and run the system without reading code.

## Non-Negotiable V1 Constraints

- Keep fake mode deterministic and fast.
- Do not let CLI or Web UI duplicate orchestration logic.
- Do not let provider-backed agents bypass artifact contracts.
- Preserve role boundaries unless a module explicitly changes the policy and docs.
- Preserve auditability: new features must write/read structured stores, not hidden transcripts.
- Keep docs and `docs/learn` in Chinese for newly implemented modules.

## Module Documents

- [18 Interactive CLI Session](modules/18-interactive-cli-session.md)
- [19 Dashboard CLI Command](modules/19-dashboard-cli-command.md)
- [20 Persistent Local Workspace](modules/20-persistent-local-workspace.md)
- [21 Real Web Collection Tools](modules/21-real-web-collection-tools.md)
- [22 Provider-Backed Model Runtime](modules/22-provider-backed-model-runtime.md)
- [23 Structured Agent Prompts](modules/23-structured-agent-prompts.md)
- [24 Full Provenance Graph](modules/24-full-provenance-graph.md)
- [25 Reliability Harness v1](modules/25-reliability-harness-v1.md)
- [26 Integrated Rework Orchestration](modules/26-integrated-rework-orchestration.md)
- [27 Basic Web Dashboard](modules/27-basic-web-dashboard.md)
- [28 Report Export Package](modules/28-report-export-package.md)
- [29 Golden Suite Expansion and CI](modules/29-golden-suite-ci.md)
- [30 Demo and Operator Polish](modules/30-demo-operator-polish.md)
