#!/usr/bin/env bash
# Single fake-money scheduled apply path. Codex researches and writes today's
# structured input; this script only validates and applies deterministic paper accounting.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONFIG="examples/fund.mandate.json"
LEDGER="state/edgecraft-fund.db"
TODAY_UTC="$(date -u +%F)"
INPUT="${FUND_INPUT:-state/fund-inputs/${TODAY_UTC}.json}"

if [[ ! -f "$INPUT" ]]; then
  echo "{\"ok\":false,\"error\":\"missing_fund_input\",\"detail\":\"$INPUT\"}" >&2
  exit 2
fi

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

"${RUN[@]}" fund-init --config "$CONFIG" --ledger "$LEDGER"
"${RUN[@]}" fund-verify --config "$CONFIG" --ledger "$LEDGER"
"${RUN[@]}" fund-run --config "$CONFIG" --input "$INPUT" --ledger "$LEDGER" \
  --require-as-of-today --max-decision-age-seconds 1800 --require-cycle-key "$TODAY_UTC"
"${RUN[@]}" fund-verify --config "$CONFIG" --ledger "$LEDGER"
