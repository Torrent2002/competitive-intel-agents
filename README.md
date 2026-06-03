# Competitive Intel Agents

AI-powered competitive analysis multi-agent collaboration system — **auditable, observable, resilient by design**.

> Not just "4 LLMs chained together." Every conclusion must have a provenance chain. Every agent decision must be replayable. The system must detect when an agent is stuck and recover autonomously.

## Design Philosophy (Why This Is Not Just Another Multi-Agent Demo)

| What Everyone Else Does | What This Project Does |
|---|---|
| Chain LLM calls, output a report | **Journal every agent decision** → full causal provenance chain |
| "The report looks good" | **Structured quality verification** with automated rework loop |
| Ignore agent failures | **Per-agent stall detection + circuit breaker + checkpoint recovery** |
| No regression testing | **Golden case replay** — same inputs, compare outputs, detect degradation |
| Logs maybe | **Per-agent observability dashboard** — rounds, tokens, tool calls, health |

These design choices come from real-world Agent Infra experience (Astra engine open-source contributions), ported here as a standalone system.

---

## Architecture

```
User Input (company name / product)
        │
        ▼
┌─────────────────────────────────────────────────┐
│              Orchestrator                         │
│   Task decomposition → DAG → Agent profiles      │
│   Assigns: budget, tools, strategy per agent      │
└────────────────────┬────────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│ Collector │   │ Analyst  │   │  Writer  │
│  Agent    │   │  Agent   │   │  Agent   │
├──────────┤   ├──────────┤   ├──────────┤
│ Role:    │   │ Role:    │   │ Role:    │
│ search + │   │ compare +│   │ struct-  │
│ scrape   │   │ insights │   │ ured     │
│          │   │          │   │ report   │
│ Tools:   │   │ Tools:   │   │ Tools:   │
│ web_search│  │ all read │   │ all read │
│ web_fetch│   │          │   │          │
│          │   │          │   │          │
│ Budget:  │   │ Budget:  │   │ Budget:  │
│ 10 rounds│   │ 15 rounds│   │ 8 rounds │
└────┬─────┘   └────┬─────┘   └────┬─────┘
     │              │              │
     └──────────────┼──────────────┘
                    ▼
┌─────────────────────────────────────────────────┐
│           Quality Reviewer Agent                 │
│   Fact-check: claim vs source → approve/reject   │
│   Logic-check: conclusion follows from evidence? │
│   Reject → structured feedback → auto rework     │
└────────────────────┬────────────────────────────┘
                     │
              ┌──────┴──────┐
              ▼              ▼
           Approve        Reject → Return to source agent
              │
              ▼
     Final Report Output
```

---

## Agent Reliability Layer

Every agent runs inside a **reliability harness** (ported from Astra engine design):

```
Agent Execution
      │
      ├─ Pre-Round: Check budget, check health
      ├─ LLM Call
      ├─ Post-Round:
      │    ├─ Stall Detection: N consecutive read-only rounds?
      │    ├─ Hallucination Tripwire: claims unsupported by tool output?
      │    ├─ Circuit Breaker: repeated identical tool calls → abort
      │    └─ Checkpoint: save state for recovery
      └─ Next Round or Terminate
```

| Mechanism | What It Catches |
|---|---|
| **Stall Detection** | Collector stuck on same page, Analyst re-reading same data |
| **Hallucination Tripwire** | Writer claims "X dominates market" but no source data supports it |
| **Circuit Breaker** | Any agent repeating identical tool calls 3+ rounds → abort with diagnostics |
| **Checkpoint Recovery** | Agent crashed mid-analysis → resume from last checkpoint, not from scratch |

### Initial Harness Scope

The first implementation keeps the harness intentionally small. The goal is to make every agent round observable and controllable before adding heavier recovery or verification logic.

**RuntimeHarness v0 responsibilities:**

1. Wrap every agent round with `pre_round` and `post_round` hooks.
2. Enforce per-agent round budgets from `agent_profiles.yaml`.
3. Append one journal event per round.
4. Track tool calls and trip a circuit breaker on repeated identical calls.
5. Save a lightweight checkpoint after each successful round.
6. Return a simple decision: `continue`, `stop`, `retry`, `rework`, or `abort`.

Minimal round event:

```json
{
  "run_id": "run_20260603_001",
  "agent": "collector",
  "round": 2,
  "tool_calls": [
    {"name": "web_fetch", "args": {"url": "https://example.com/report"}}
  ],
  "output_artifact_ids": ["source_003"],
  "signals": ["progress"],
  "decision": "continue",
  "timestamp": "2026-06-03T14:22:01Z"
}
```

In v0, the hallucination tripwire is conservative: it only checks claims that already declare source references. Deeper claim extraction and semantic verification can come later, after the journal and artifact contracts are stable.

---

## Provenance & Audit

Every claim in the final report must be traceable:

```
Report claim: "Competitor X has 35% market share in APAC"
        │
        ▼
    Analyst Agent, Round 4
    → Inferred from data provided by Collector Agent
        │
        ▼
    Collector Agent, Round 2
    → web_fetch("https://example.com/market-report-2026")
    → Timestamp: 2026-06-03T14:22:01Z
    → Raw snippet: "Company X holds 35% of APAC market..."
```

**Journal structure** (per agent, per round):
```json
{
  "agent": "collector",
  "round": 2,
  "tool_call": {"name": "web_fetch", "args": {"url": "..."}},
  "tool_result_preview": "Company X holds 35%...",
  "timestamp": "2026-06-03T14:22:01Z",
  "causal_parent": "orchestrator.task_decomposition.round_0"
}
```

In Phase 1, every factual claim should carry source ids. In later phases, each source id is expanded into a full `causal_chain` back through the journal events that created it. No final factual claim should be emitted without source references.

---

## Quality Dimensions (Pass Criteria)

| Dimension | Metric | Target |
|---|---|---|
| **Completeness** | Required sections present (overview, features, pricing, SWOT, etc.) | 100% |
| **Source Coverage** | Factual claims backed by ≥1 source id | 100% |
| **Factual Accuracy** | Quality Reviewer pass rate | ≥ 90% |
| **Agent Health** | Tasks completed without circuit breaker trip | ≥ 95% |
| **Cost Efficiency** | Avg tokens per analysis | tracked, not gated |
| **Golden Regression** | Degradation on curated test cases | ≤ 5% |

---

## Golden Case Regression

A curated set of known-good inputs with expected output structure:

1. Run full pipeline on golden cases
2. Compare: did any agent stall? did quality reviewer reject more? did token cost spike?
3. Detect silent regressions before they hit users

```
tests/golden/
├── case_01_single_competitor/
│   ├── input.json       # {"company": "Notion", "market": "productivity"}
│   └── expected.json    # schema expectations, not exact text match
├── case_02_multi_competitor/
│   └── ...
└── ...
```

---

## Observability

Per-run dashboard (terminal or basic web):

```
┌─────────────────────────────────────────────────────┐
│  Run: notion-competitive-analysis-20260603           │
│  Status: ✅ Complete   Duration: 3m42s               │
├─────────────────────────────────────────────────────┤
│  Collector │ ████████░░  8/10 rounds  │ ✅ Healthy  │
│  Analyst   │ ██████████ 10/15 rounds  │ ⚠ Stall x1  │
│  Writer    │ ██████░░░░  5/8 rounds   │ ✅ Healthy  │
│  Reviewer  │ ██░░░░░░░░  2/4 reviews  │ 1 rework    │
├─────────────────────────────────────────────────────┤
│  Total Tokens: 48,200   Cost: ~$0.25                │
│  Sources Collected: 12   Claims Verified: 34/38     │
└─────────────────────────────────────────────────────┘
```

---

## Tech Stack

- **Runtime**: Python 3.12+ (agent loop, orchestration, reliability harness)
- **LLM**: Anthropic Claude (primary), OpenAI compatible (fallback)
- **Storage**: SQLite (local) / PostgreSQL (production)
- **Frontend**: Terminal dashboard (rich/textual) + optional Web UI
- **Testing**: pytest + golden case replay harness

---

## Project Structure (Planned)

```
competitive-intel-agents/
├── src/
│   ├── agents/           # Collector, Analyst, Writer, Reviewer
│   ├── orchestrator/     # Task decomposition, DAG, agent profiles
│   ├── runtime/          # Model/tool execution
│   ├── journal/          # Decision record, provenance chain
│   ├── harness/          # RuntimeHarness, signals, budgets, checkpoint
│   ├── cli/              # Command-line entrypoint
│   └── dashboard/        # Observability UI
├── tests/
│   ├── golden/           # Golden case regression suite
│   ├── fixtures/         # Fake requests and expected shapes
│   └── unit/             # Per-component tests
├── docs/
│   ├── SPEC_CODING_PLAN.md
│   └── modules/          # Small module specs for incremental development
├── config/
│   └── agent_profiles.yaml
└── README.md
```

For incremental implementation, see the [Spec Coding Plan](docs/SPEC_CODING_PLAN.md). It breaks the system into small modules with goals, public contracts, tests, and done criteria.

---

## Project Status

**Phase 1 (current)**: Core pipeline + minimal harness — single agent loop, basic 4-agent orchestration, end-to-end flow, round journaling, budget checks, repeated-tool circuit breaker.

**Phase 2**: Reliability layer — stronger stall detection, checkpoint recovery per agent, retry policies.

**Phase 3**: Provenance — full causal chain, audit trail, claim-to-source traceability beyond Phase 1 source ids.

**Phase 4**: Quality system — structured reviewer feedback loop, golden case regression.

---

## Inspiration

Design patterns drawn from [Astra Engine](https://github.com/matrixorigin/astra-suite) open-source contributions:
- Harness signal system & behavior verification
- Circuit breaker with progress-aware stall detection
- Journal-based event sourcing for audit
- Checkpoint injection for autonomous recovery
