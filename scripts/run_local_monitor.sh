#!/usr/bin/env bash
# Model-free five-minute loop for the dedicated local runtime checkout:
# enforce exits and settlements, score forecasts, and run the code-only
# baseline fund (which limits itself to one scan per policy interval).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p state
if [[ "${EDGECRAFT_LEDGER_LOCKED:-0}" != "1" ]] && command -v lockf >/dev/null 2>&1; then
  export EDGECRAFT_LEDGER_LOCKED=1
  exec lockf -t 300 -k state/.paper-ledger.lock "$0" "$@"
fi

RUN=("$ROOT/.venv/bin/edgecraft")
LEDGER="state/edgecraft-aggressive.db"
RESEARCH="examples/fund.mandate.facts.json"
# Winding down: no new entries (its drawdown gate refuses them), but its open
# positions still need exits and settlement, and its forecasts still settle.
PREDICTIONS="examples/fund.mandate.predictions.json"
BASELINE="examples/fund.mandate.baseline.json"

for CONFIG in "$RESEARCH" "$PREDICTIONS" "$BASELINE"; do
  "${RUN[@]}" fund-init --config "$CONFIG" --ledger "$LEDGER" >/dev/null
  "${RUN[@]}" fund-verify --config "$CONFIG" --ledger "$LEDGER"
  "${RUN[@]}" monitor --config "$CONFIG" --ledger "$LEDGER"
  "${RUN[@]}" fund-forecast-score --config "$CONFIG" --ledger "$LEDGER"
done
"${RUN[@]}" fund-baseline --config "$BASELINE" --ledger "$LEDGER"
for CONFIG in "$RESEARCH" "$PREDICTIONS" "$BASELINE"; do
  "${RUN[@]}" fund-verify --config "$CONFIG" --ledger "$LEDGER"
done
"${RUN[@]}" fund-report --config "$RESEARCH" --ledger "$LEDGER" \
  --output state/fund-report.json
"${RUN[@]}" fund-report --config "$PREDICTIONS" --ledger "$LEDGER" \
  --output state/fund-report-edgecraft-predictions.json
"${RUN[@]}" fund-report --config "$BASELINE" --ledger "$LEDGER" \
  --output state/fund-report-edgecraft-baseline.json
"${RUN[@]}" fund-alerts --config "$RESEARCH" --ledger "$LEDGER"
"${RUN[@]}" fund-alerts --config "$BASELINE" --ledger "$LEDGER"
