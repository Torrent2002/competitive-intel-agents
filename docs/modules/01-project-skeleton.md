# 01 Project Skeleton

## Goal

Create the repository layout for a Python package that can support agents, runtime execution, harness logic, journals, artifacts, configuration, and tests.

## Scope

In scope:

- Python package layout under `src/`.
- Test layout under `tests/`.
- Fixture layout under `tests/fixtures/`.
- Config layout under `config/`.
- Basic packaging files.

Out of scope:

- Real agent logic.
- Real model calls.
- Real persistence beyond placeholder modules.

## Expected Structure

```text
src/
  competitive_intel_agents/
    agents/
    artifacts/
    dashboard/
    harness/
    journal/
    orchestrator/
    runtime/
config/
  agent_profiles.yaml
tests/
  fixtures/
    request.json
  unit/
  golden/
```

## Public Contract

The package should be importable:

```python
import competitive_intel_agents
```

The CLI command should be registered, even if it only runs a fake pipeline at first:

```text
competitive-intel run --input tests/fixtures/request.json
```

## Suggested Files

- `pyproject.toml`
- `src/competitive_intel_agents/__init__.py`
- `config/agent_profiles.yaml`
- `tests/fixtures/request.json`
- `tests/unit/test_imports.py`

## Tests

- Verify the package imports.
- Verify expected top-level modules import.
- Verify `config/agent_profiles.yaml` exists.
- Verify `tests/fixtures/request.json` exists and has valid JSON.

## Done Criteria

- `pytest` runs.
- Package imports from a clean checkout.
- CLI entrypoint is registered.
- No agent behavior is implemented yet.
