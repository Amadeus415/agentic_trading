#!/usr/bin/env bash
# Check the installed runtime offline. Deploy code/dependencies with --update.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--update" ) ]]; then
  echo "Usage: $0 [--update]" >&2
  exit 2
fi

if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "Local runtime must stay on the main branch." >&2
  exit 2
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Local runtime has tracked changes; refusing to update." >&2
  git status --short >&2
  exit 2
fi

if [[ "${1:-}" == "--update" ]]; then
  git pull --ff-only origin main
  uv sync --frozen
fi

RUN="$ROOT/.venv/bin/edgecraft"
if [[ ! -x "$RUN" ]]; then
  echo "Runtime environment missing; run $0 --update during deployment." >&2
  exit 2
fi

"$RUN" fund-init \
  --config examples/fund.mandate.aggressive.json \
  --ledger state/edgecraft-aggressive.db
"$RUN" fund-verify \
  --config examples/fund.mandate.aggressive.json \
  --ledger state/edgecraft-aggressive.db
"$RUN" fund-report \
  --config examples/fund.mandate.aggressive.json \
  --ledger state/edgecraft-aggressive.db \
  --output state/fund-report.json
