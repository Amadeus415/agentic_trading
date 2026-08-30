#!/usr/bin/env bash
# Single fake-money scheduled apply path. Codex researches and writes this
# session's structured input; this script only validates and applies
# deterministic paper accounting.
#
# Session slots (UTC) must stay in sync with src/edgecraft/schedule.py:
#   13-16 session-eu | 16-20 session-us-open | 20-23 session-us-close | else offhours
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONFIG="${FUND_CONFIG:-examples/fund.mandate.aggressive.json}"
LEDGER="${FUND_LEDGER:-state/edgecraft-aggressive.db}"
HOUR=$((10#$(date -u +%H)))
DATE_UTC="$(date -u +%F)"
if (( HOUR >= 13 && HOUR < 16 )); then
  SLOT="session-eu"
elif (( HOUR >= 16 && HOUR < 20 )); then
  SLOT="session-us-open"
elif (( HOUR >= 20 && HOUR < 23 )); then
  SLOT="session-us-close"
else
  SLOT="session-offhours"
fi
CYCLE_KEY="${DATE_UTC}-${SLOT}"
INPUT="${FUND_INPUT:-state/fund-inputs/${CYCLE_KEY}.json}"

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
  --require-as-of-today --max-decision-age-seconds 1800 --require-cycle-key "$CYCLE_KEY" \
  --require-brain-journal
"${RUN[@]}" fund-verify --config "$CONFIG" --ledger "$LEDGER"
