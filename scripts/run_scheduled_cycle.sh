#!/usr/bin/env bash
# Single fail-closed scheduled wake path for Codex / cron.
# health (hard fail) → readiness --require-ready → cycle
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LEDGER="${LEDGER:-state/edgecraft.db}"
# Shadow-default mandate. Override MANDATE only for an explicitly armed live path.
MANDATE="${MANDATE:-examples/mandate.index-dca.json}"
REAL_DATA_SYMBOL="${REAL_DATA_SYMBOL:-SPY}"

if command -v uv >/dev/null 2>&1; then
  RUN=(uv run edgecraft)
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
"${RUN[@]}" cycle --mandate "$MANDATE" --ledger "$LEDGER"
