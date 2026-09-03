#!/usr/bin/env bash
# Model-free hourly monitoring for the dedicated local runtime checkout.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p state
if [[ "${EDGECRAFT_LEDGER_LOCKED:-0}" != "1" ]] && command -v lockf >/dev/null 2>&1; then
  export EDGECRAFT_LEDGER_LOCKED=1
  exec lockf -t 300 -k state/.paper-ledger.lock "$0" "$@"
fi

RUN=(uv run --no-sync edgecraft)
CONFIG="examples/fund.mandate.aggressive.json"
LEDGER="state/edgecraft-aggressive.db"

"${RUN[@]}" fund-verify --config "$CONFIG" --ledger "$LEDGER"
"${RUN[@]}" monitor --config "$CONFIG" --ledger "$LEDGER"
"${RUN[@]}" fund-verify --config "$CONFIG" --ledger "$LEDGER"
"${RUN[@]}" fund-report --config "$CONFIG" --ledger "$LEDGER" \
  --output state/fund-report.json
"${RUN[@]}" fund-alerts --config "$CONFIG" --ledger "$LEDGER"
