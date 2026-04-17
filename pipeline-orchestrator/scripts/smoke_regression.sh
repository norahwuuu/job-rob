#!/usr/bin/env bash
set -euo pipefail

# Minimal regression flow (safe scale)
# Usage:
#   bash scripts/smoke_regression.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PY="./.venv/bin/python"

echo "[1/4] Status check"
$PY pipeline-orchestrator/run_pipeline.py status

echo "[2/4] Generate one resume"
$PY pipeline-orchestrator/run_pipeline.py generate --limit 1

echo "[3/4] Apply one easy todo entry"
$PY pipeline-orchestrator/run_pipeline.py apply --max 1

echo "[4/4] Final status"
$PY pipeline-orchestrator/run_pipeline.py status

echo "Smoke regression completed."
