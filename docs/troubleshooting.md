# Troubleshooting

## Homebrew Python and SSL certificate errors

If `pip install -e .` fails with SSL certificate errors on macOS:

```bash
# Option 1: Use PYTHONPATH fallback (no install needed)
PYTHONPATH=src python -m competitive_intel_agents.cli run \
  --input tests/fixtures/request.json

# Option 2: Install with trusted host
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -e .
```

## Editable install fails on system Python

If you installed Python via Homebrew and `pip install -e .` complains:

```bash
# Create a virtual environment first
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## PYTHONPATH not working

The project requires `PYTHONPATH=src` when running without editable install:

```bash
# Correct
PYTHONPATH=src python -m competitive_intel_agents.cli run --input tests/fixtures/request.json

# Also correct (from project root)
PYTHONPATH=src python3 -m competitive_intel_agents.cli run --input tests/fixtures/request.json
```

If you get `ModuleNotFoundError: No module named 'competitive_intel_agents'`, make sure:
1. You're running from the project root directory.
2. `PYTHONPATH=src` is set (not `PYTHONPATH=src/competitive_intel_agents`).

## Tests fail with import errors

Run tests from the project root:

```bash
cd competitive-intel-agents
python3 -m pytest tests/ -v
```

The `pyproject.toml` configures `pythonpath = ["src"]` for pytest.

## Web dashboard port already in use

```bash
# Use a different port
competitive-intel web --port 9090

# Or find and kill the existing process
lsof -i :8080
```

## Workspace shows empty runs

Make sure you passed `--workspace` when running the pipeline:

```bash
competitive-intel run --input tests/fixtures/request.json --workspace .competitive-intel
competitive-intel runs --workspace .competitive-intel
```

## Golden suite failures

Golden cases are deterministic in fake mode. If they fail:

1. Check that you haven't modified the fake agent behavior.
2. Run a specific case to see detailed metrics:
   ```bash
   competitive-intel golden --root tests/golden
   ```
3. Each failure prints the metric name, expected value, and actual value.
