#!/usr/bin/env bash
# Single paper-only, fail-closed scheduled wake path for Codex / cron.
# health (hard fail) → readiness --require-ready → cycle
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LEDGER="${LEDGER:-state/edgecraft-paper.db}"
# Fixed shadow mandate: scheduled operation cannot be redirected to live trading.
MANDATE="examples/mandate.index-dca.json"
REAL_DATA_SYMBOL="${REAL_DATA_SYMBOL:-SPY}"

if command -v uv >/dev/null 2>&1; then
  # Scheduled runs must not resolve dependencies or require package-network access.
  RUN=(uv run --no-sync edgecraft)
else
  # Fallback when uv is unavailable but PYTHONPATH/venv is configured.
  export PYTHONPATH="${PYTHONPATH:-}:${ROOT}/src"
  if [[ -x "${ROOT}/.venv/bin/edgecraft" ]]; then
    RUN=("${ROOT}/.venv/bin/edgecraft")
  else
    RUN=(python -m edgecraft)
  fi
fi

"${RUN[@]}" health --real-data-symbol "$REAL_DATA_SYMBOL" --ledger "$LEDGER"
"${RUN[@]}" readiness --mandate "$MANDATE" --ledger "$LEDGER" --require-ready
"${RUN[@]}" cycle --mandate "$MANDATE" --ledger "$LEDGER" --paper-only
