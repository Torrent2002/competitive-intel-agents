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

Out of scope:

- Web server.
- Authentication.
- Long-running job scheduling.

## Command v0

```text
competitive-intel run --input tests/fixtures/request.json
```

Optional flags:

- `--config config/agent_profiles.yaml`
- `--fake-model`
- `--output out/report.md`

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

## Done Criteria

- A developer can run the first end-to-end fake pipeline with one command.
- CLI code is thin and delegates orchestration to `Orchestrator`.

