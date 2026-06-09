#!/usr/bin/env bash
# Demo script: runs the full competitive intel pipeline end to end.
#
# Usage:
#   bash scripts/demo.sh
#
# Requirements:
#   - Python 3.12+
#   - No pip install needed (uses PYTHONPATH=src)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

export PYTHONPATH="$PROJECT_DIR/src"

PYTHON_BIN="${PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
    if command -v python3.12 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3.12)"
    elif [ -x /opt/homebrew/bin/python3.12 ]; then
        PYTHON_BIN="/opt/homebrew/bin/python3.12"
    else
        PYTHON_BIN="$(command -v python3 || true)"
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "Error: Python 3.12+ is required, but no Python interpreter was found."
    exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit(
        f"Error: Python 3.12+ is required, got {sys.version.split()[0]}. "
        "Set PYTHON=/path/to/python3.12 or install python3.12."
    )
PY

echo "Python: $($PYTHON_BIN --version)"

# Ensure test fixtures exist
FIXTURE="$PROJECT_DIR/tests/fixtures/request.json"
if [ ! -f "$FIXTURE" ]; then
    echo "Error: fixture not found: $FIXTURE"
    exit 1
fi

# Prepare temp workspace
WORKSPACE="$(mktemp -d)/.competitive-intel"
echo "=== Competitive Intel Agents Demo ==="
echo "Workspace: $WORKSPACE"
echo ""

# 1. Run the fake pipeline
echo "--- Step 1: Run pipeline ---"
"$PYTHON_BIN" -m competitive_intel_agents.cli run \
    --input "$FIXTURE" \
    --config config/agent_profiles.yaml \
    --fake-model \
    --workspace "$WORKSPACE" \
    --show-dashboard \
    --output "$WORKSPACE/report.md"
echo ""

# 2. List runs
echo "--- Step 2: List runs ---"
"$PYTHON_BIN" -m competitive_intel_agents.cli runs \
    --workspace "$WORKSPACE"
echo ""

# 3. Get the run ID from the workspace
RUN_ID=$("$PYTHON_BIN" -c "
import json
from pathlib import Path
runs = json.loads(Path('$WORKSPACE/runs.json').read_text())
print(runs[-1]['run_id'] if runs else '')
")
if [ -z "$RUN_ID" ]; then
    echo "Error: no run found in workspace"
    exit 1
fi
echo "Latest run: $RUN_ID"
echo ""

# 4. Show dashboard
echo "--- Step 3: Dashboard ---"
"$PYTHON_BIN" -m competitive_intel_agents.cli dashboard \
    --run-id "$RUN_ID" \
    --workspace "$WORKSPACE"
echo ""

# 5. Export report as JSON
echo "--- Step 4: Export JSON ---"
"$PYTHON_BIN" -m competitive_intel_agents.cli export \
    --run-id "$RUN_ID" \
    --format json \
    --workspace "$WORKSPACE" \
    --output "$WORKSPACE/report.json"
echo "Exported JSON: $WORKSPACE/report.json"
echo ""

# 6. Export report as HTML
echo "--- Step 5: Export HTML ---"
"$PYTHON_BIN" -m competitive_intel_agents.cli export \
    --run-id "$RUN_ID" \
    --format html \
    --workspace "$WORKSPACE" \
    --output "$WORKSPACE/report.html"
echo "Exported HTML: $WORKSPACE/report.html"
echo ""

# 7. Run golden suite
echo "--- Step 6: Golden Suite ---"
"$PYTHON_BIN" -m competitive_intel_agents.cli golden \
    --root tests/golden
GOLDEN_EXIT=$?
echo ""

echo "=== Demo Complete ==="
echo "Outputs:"
echo "  Markdown report: $WORKSPACE/report.md"
echo "  JSON export:     $WORKSPACE/report.json"
echo "  HTML export:     $WORKSPACE/report.html"
echo "  Workspace:       $WORKSPACE"

if [ $GOLDEN_EXIT -eq 0 ]; then
    echo "  Golden suite:    ALL PASSED"
else
    echo "  Golden suite:    FAILURES DETECTED (exit $GOLDEN_EXIT)"
fi
