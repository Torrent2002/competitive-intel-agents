# 18 Interactive CLI Session

## Goal

Provide an interactive terminal session where a user can enter a competitive
analysis request, run the agent workflow, and inspect results without writing
JSON by hand.

## Why It Matters

The current CLI is command-oriented:

```text
competitive-intel run --input request.json
```

That proves the pipeline works, but it does not feel like interacting with an
agent system. This module creates the first real operator-facing interaction
surface.

## Scope

In scope:

- `competitive-intel chat` command.
- Prompt for company, market, competitors, and focus questions.
- Run the existing `Orchestrator`.
- Keep the latest run in session memory.
- Interactive commands:
  - `dashboard`
  - `report`
  - `sources`
  - `claims`
  - `feedback`
  - `save <path>`
  - `new`
  - `exit`
- Friendly empty-state messages.
- Optional `--workspace` persistence.

Out of scope:

- Natural-language command parsing.
- Multi-run history browsing.
- Web UI.
- Real model streaming.

## Public Interface

```text
competitive-intel chat
```

Optional flags:

- `--config config/agent_profiles.yaml`
- `--fake-model`
- `--workspace .competitive-intel`

Example session:

```text
Company: Notion
Market: productivity
Competitors: Coda, Airtable
Questions: pricing, collaboration features

Run status: approved
Type: dashboard, report, sources, claims, save <path>, new, exit
> dashboard
...
> report
...
```

## Tests

- Starts an interactive session through subprocess stdin.
- Prompts for request fields.
- Runs fake pipeline and prints approved status.
- `dashboard` prints terminal dashboard output.
- `report` prints report sections.
- `sources` and `claims` print artifact ids.
- `save <path>` writes markdown.
- `exit` terminates cleanly.
- Optional workspace writes the run result for later dashboard lookup.

## Done Criteria

- A user can experience the end-to-end workflow entirely inside CLI.
- CLI remains a thin adapter over Orchestrator, Dashboard, and ArtifactStore.
- README interactive examples match actual behavior.
