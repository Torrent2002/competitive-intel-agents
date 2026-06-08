# Competitive Intel Agents

Evidence-first competitive intelligence workflow — **auditable, source-backed, role-bounded, and replayable by design**.

> This project is not trying to prove that four agents are magically smarter than one agent. A single agent can search, analyze, and write a report. The point here is different: turn competitive analysis into a controlled production workflow where every claim has evidence, every intermediate artifact is inspectable, every rejection can trigger bounded rework, and every run can be replayed.

## Design Philosophy (Why This Is Not Just Another Multi-Agent Demo)

| What Everyone Else Does | What This Project Does |
|---|---|
| Let one agent search, reason, and write | **Role-bounded workflow**: Collector gathers sources, Analyst writes sourced claims, Writer drafts, Reviewer checks |
| Trust the final prose | **Evidence-first artifacts**: final report claims must trace to `source_ids` |
| Ask the same agent to review itself | **Independent reviewer feedback** routed back to the responsible stage |
| Rerun the whole prompt when something is wrong | **Bounded rework**: replace only the stale artifact and rerun downstream stages |
| Keep ad hoc logs | **Replayable journal**: every round has decision, tool calls, signals, and artifact ids |
| Compare exact generated text | **Golden replay metrics**: source coverage, schema completeness, rejections, rounds, tool calls |

These design choices come from real-world Agent Infra experience (Astra engine open-source contributions), ported here as a standalone system.

---

## Why Multi-Agent Here?

The value of this project is not "more agents means more intelligence." The value is engineering control.

A single agent can produce a competitive report, but it tends to blur responsibilities: it can fetch evidence, infer claims, write narrative, and judge quality in one opaque chain. That makes it hard to answer practical questions:

- Which source supports this claim?
- Did the writer invent facts that the collector never found?
- Can we fix one unsupported claim without rerunning the whole report?
- Did this change make our source coverage worse?
- Why did the system retry, abort, or ask for rework?

This system makes those questions first-class:

- `SourceArtifact` records what was collected.
- `AnalysisClaim` must carry `source_ids`.
- `ReportDraft` is built from claims, not raw hidden context.
- `ReviewFeedback` targets a specific agent and artifact.
- `RoundEvent` records each agent decision for audit and replay.

In other words: the agent runtime is the engine; this project is the domain-specific production line around it.

## Architecture

```
User Input (company name / product)
        │
        ▼
┌─────────────────────────────────────────────────┐
│              Orchestrator                       │
│   Builds run context, stores, profiles, DAG      │
│   Enforces role sequence and rework boundaries   │
└────────────────────┬────────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│ Collector │   │ Analyst  │   │  Writer  │
│  Agent    │   │  Agent   │   │  Agent   │
├──────────┤   ├──────────┤   ├──────────┤
│ Writes:  │   │ Writes:  │   │ Writes:  │
│ Source-  │   │ sourced  │   │ report   │
│ Artifact │   │ claims   │   │ draft    │
│          │   │          │   │          │
│ Tools:   │   │ Tools:   │   │ Tools:   │
│ search + │   │ none     │   │ none     │
│ fetch    │   │          │   │          │
└────┬─────┘   └────┬─────┘   └────┬─────┘
     │              │              │
     └──────────────┼──────────────┘
                    ▼
┌─────────────────────────────────────────────────┐
│           Quality Reviewer Agent                 │
│   Checks claim source coverage and report shape  │
│   Rejects with target agent + artifact id        │
│   Feedback drives bounded downstream rework      │
└────────────────────┬────────────────────────────┘
                     │
              ┌──────┴──────┐
              ▼              ▼
           Approve        Reject → Return to source agent
              │
              ▼
     Source-backed Final Report
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
6. Pass tool results into the next round through agent memory.
7. Return a simple decision: `continue`, `stop`, `retry`, `rework`, or `abort`.

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

In Phase 1, every factual claim must carry source ids. In later phases, each source id is expanded into a full `causal_chain` back through the journal events that created it. No final factual claim should be emitted without source references.

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

## Project Structure

```
competitive-intel-agents/
├── src/competitive_intel_agents/
│   ├── agents/           # Collector, Analyst, Writer, Reviewer
│   ├── artifacts/        # Artifact store (in-memory and SQLite)
│   ├── cli/              # CLI (run/chat/dashboard/export/web/golden/runs)
│   ├── dashboard/        # Terminal dashboard snapshot
│   ├── export/           # Report export (markdown, JSON, HTML)
│   ├── golden/           # Golden replay runner and metrics
│   ├── harness/          # RuntimeHarness, checkpoint, stall detection
│   ├── journal/          # Journal store (in-memory and SQLite)
│   ├── orchestrator/     # Pipeline orchestrator and agent DAG
│   ├── prompts/          # Structured agent prompts
│   ├── provenance/       # Causal provenance graph
│   ├── rework/           # Bounded rework loop
│   ├── runtime/          # Model/tool runtime and web tools
│   ├── web/              # Web dashboard (stdlib http.server)
│   ├── workspace/        # Persistent local workspace
│   └── models.py         # Shared data contracts
├── tests/
│   ├── golden/           # 5 golden cases for CI regression
│   ├── fixtures/         # Fake requests
│   └── unit/             # 25+ unit test files
├── docs/
│   ├── learn/            # Chinese learning docs (00-30)
│   ├── modules/          # Module specs (01-30)
│   └── troubleshooting.md
├── scripts/
│   └── demo.sh           # End-to-end demo
├── config/
│   └── agent_profiles.yaml
└── README.md
```

For incremental implementation, see the [Spec Coding Plan](docs/SPEC_CODING_PLAN.md). It breaks the system into small modules with goals, public contracts, tests, and done criteria.

## Local Usage

Run a one-shot fake pipeline:

```bash
PYTHONPATH=src python -m competitive_intel_agents.cli run \
  --input tests/fixtures/request.json \
  --config config/agent_profiles.yaml \
  --fake-model \
  --output out/report.md
```

Run an interactive terminal session:

```bash
PYTHONPATH=src python -m competitive_intel_agents.cli chat
```

Enable optional real Web collection for run or chat:

```bash
PYTHONPATH=src python -m competitive_intel_agents.cli run \
  --input tests/fixtures/request.json \
  --workspace .competitive-intel \
  --real-web \
  --show-dashboard
```

Persist a run and inspect it later:

```bash
PYTHONPATH=src python -m competitive_intel_agents.cli run \
  --input tests/fixtures/request.json \
  --workspace .competitive-intel \
  --show-dashboard

PYTHONPATH=src python -m competitive_intel_agents.cli runs \
  --workspace .competitive-intel

PYTHONPATH=src python -m competitive_intel_agents.cli dashboard \
  --run-id run_xxx \
  --workspace .competitive-intel
```

Export a completed run:

```bash
PYTHONPATH=src python -m competitive_intel_agents.cli export \
  --run-id <run_id> \
  --format markdown|json|html \
  --workspace .competitive-intel \
  --output report.md
```

Run the golden regression suite:

```bash
PYTHONPATH=src python -m competitive_intel_agents.cli golden \
  --root tests/golden
```

Start a local web dashboard:

```bash
PYTHONPATH=src python -m competitive_intel_agents.cli web \
  --workspace .competitive-intel \
  --port 8080
```

Run the full demo script:

```bash
bash scripts/demo.sh
```

If editable install fails because of a system Python or certificate issue, the
`PYTHONPATH=src python -m ...` form is the supported fallback.

Provider-backed model runtime is available behind environment configuration.
By default the project uses deterministic fake model output.

```bash
export CIA_MODEL_PROVIDER=openai-compatible
export CIA_MODEL_ENDPOINT=https://api.example.com/v1/chat/completions
export CIA_MODEL_API_KEY=your_api_key
export CIA_MODEL_NAME=your_model_name
```

---

## Quickstart

```bash
# Clone and enter the project
git clone https://github.com/Torrent2002/competitive-intel-agents.git
cd competitive-intel-agents

# Option A: Venv + editable install
python3 -m venv .venv && source .venv/bin/activate && pip install -e .

# Option B: PYTHONPATH (no install)
export PYTHONPATH=src

# Run the demo
bash scripts/demo.sh

# Or run individual commands
competitive-intel run --input tests/fixtures/request.json --show-dashboard
competitive-intel chat
competitive-intel web --port 8080
```

See [troubleshooting](docs/troubleshooting.md) for common issues.

---

## Project Status

**V1 (current)**: Full pipeline with role-bounded agents, CLI suite (run/chat/dashboard/export/web/golden), persistence, provenance, golden replay CI, and web dashboard.

**Phase 1**: Role-bounded artifact pipeline — source collection, sourced claims, structured draft, reviewer gate, round journaling, budget checks, repeated-tool circuit breaker.

**Phase 2**: Reliability layer — stall detection, checkpoint recovery per agent, retry policies, integrated rework orchestration.

**Phase 3**: Provenance — full causal chain, audit trail, claim-to-source traceability.

**Phase 4**: Quality system — structured reviewer feedback loop, golden case regression (5 cases).

---

## Inspiration

Design patterns drawn from [Astra Engine](https://github.com/matrixorigin/astra-suite) open-source contributions:
- Harness signal system & behavior verification
- Circuit breaker with progress-aware stall detection
- Journal-based event sourcing for audit
- Checkpoint injection for autonomous recovery
