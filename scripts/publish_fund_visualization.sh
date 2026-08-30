#!/usr/bin/env bash
# Publish only the generated public SVG. Fund state and inputs remain local and ignored.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ASSET="assets/fund-progress.svg"
if [[ ! -f "$ASSET" ]]; then
  echo "Run make fund-visualize before publishing." >&2
  exit 2
fi
if git diff --quiet -- "$ASSET" && git diff --cached --quiet -- "$ASSET"; then
  echo "Fund visualization is already current."
  exit 0
fi

git add -- "$ASSET"
git commit --only --message "Update the verified paper-fund progress snapshot." -- "$ASSET"
git push origin HEAD
