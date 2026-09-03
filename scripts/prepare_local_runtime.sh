#!/usr/bin/env bash
# Fast-forward a dedicated local runtime checkout to origin/main and install its
# locked dependencies. Generated state is gitignored and remains untouched.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "Local runtime must stay on the main branch." >&2
  exit 2
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Local runtime has tracked changes; refusing to update." >&2
  git status --short >&2
  exit 2
fi

git pull --ff-only origin main
uv sync --frozen
uv run --no-sync edgecraft fund-init \
  --config examples/fund.mandate.aggressive.json \
  --ledger state/edgecraft-aggressive.db
uv run --no-sync edgecraft fund-verify \
  --config examples/fund.mandate.aggressive.json \
  --ledger state/edgecraft-aggressive.db
uv run --no-sync edgecraft fund-report \
  --config examples/fund.mandate.aggressive.json \
  --ledger state/edgecraft-aggressive.db \
  --output state/fund-report.json
