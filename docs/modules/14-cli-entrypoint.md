# 14 CLI Entrypoint

## Goal

Provide one command that runs the fake or local pipeline from a request file.

## Scope

In scope:

- CLI command definition.
- Input JSON loading.
- Config loading.
- Fake pipeline execution.
- Human-readable run summary.
- Optional Markdown report output.
- Friendly validation errors for bad input files.

Out of scope:

- Web server.
- Authentication.
- Long-running job scheduling.
- Implementing orchestration logic inside CLI.

## Command v0

```text
competitive-intel run --input tests/fixtures/request.json
```

Optional flags:

- `--config config/agent_profiles.yaml`
- `--fake-model` (explicitly selects the local fake pipeline in v0; no external API keys are required)
- `--output out/report.md`

## Behavior v0

The CLI is a thin adapter:

```text
JSON file -> CompetitiveIntelRequest -> Orchestrator.run() -> summary/output
```

It must not create the DAG manually or call agents directly. Orchestration stays
inside `Orchestrator`.

On success, stdout includes:

```text
Loaded request: <path>
Run id: <run_id>
Run status: <approved|needs_rework|aborted>
Sources: <count>
Claims: <count>
Report id: <report_id>
```

If reviewer feedback exists, stdout also includes:

```text
Review feedback: <count>
```

When `--output` is provided, the CLI writes a Markdown report generated from the
latest `ReportDraft.sections`.

## Error Handling v0

- Missing input file: argparse error.
- Missing config file: argparse error.
- Invalid JSON: argparse error containing `invalid JSON`.
- Invalid request shape: argparse error containing `invalid request`.

Errors should be readable command-line failures, not Python tracebacks.

## Input Fixture

```json
{
  "company": "Notion",
  "market": "productivity",
  "competitors": ["Coda", "Airtable"],
  "questions": ["pricing", "collaboration features"]
}
```

## Tests

- CLI loads a valid request file.
- CLI rejects invalid JSON.
- CLI runs the fake pipeline without API keys.
- CLI prints `run_id`, status, source count, claim count, and report id.
- CLI accepts `--config` and `--fake-model`.
- CLI writes Markdown report when `--output` is provided.

## Done Criteria

- A developer can run the first end-to-end fake pipeline with one command.
- CLI code is thin and delegates orchestration to `Orchestrator`.
- CLI output is useful enough for local smoke testing and interview demos.
- CLI failures are understandable without reading a traceback.
