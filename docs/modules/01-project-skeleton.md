# 01 Project Skeleton

## Goal

Create the repository layout for a Python package that can support agents, runtime execution, harness logic, journals, artifacts, configuration, and tests.

## Scope

In scope:

- Python package layout under `src/`.
- Test layout under `tests/`.
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
  unit/
  golden/
```

## Public Contract

The package should be importable:

```python
import competitive_intel_agents
```

## Suggested Files

- `pyproject.toml`
- `src/competitive_intel_agents/__init__.py`
- `config/agent_profiles.yaml`
- `tests/unit/test_imports.py`

## Tests

- Verify the package imports.
- Verify expected top-level modules import.
- Verify `config/agent_profiles.yaml` exists.

## Done Criteria

- `pytest` runs.
- Package imports from a clean checkout.
- No agent behavior is implemented yet.

