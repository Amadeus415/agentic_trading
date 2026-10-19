#!/usr/bin/env bash
# Run one headless Claude Code research or review session in the runtime
# checkout. The prompt is read from docs/SCHEDULED_TASKS.md so the doc stays
# the single source; the session follows that doc and stops.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

case "${1:-}" in
  research) HEADING="## Research prompt" ;;
  review) HEADING="## Review prompt" ;;
  *) echo "Usage: $0 research|review" >&2; exit 2 ;;
esac

mkdir -p state/logs
# One Claude session at a time: a run that finds another still going skips.
if [[ "${EDGECRAFT_CLAUDE_LOCKED:-0}" != "1" ]]; then
  export EDGECRAFT_CLAUDE_LOCKED=1
  exec lockf -s -t 0 -k state/.claude-task.lock "$0" "$@"
fi

PROMPT="$(awk -v h="$HEADING" '$0 == h {found=1; next} found && /^> / {sub(/^> /, ""); print; exit}' docs/SCHEDULED_TASKS.md)"
if [[ -z "$PROMPT" ]]; then
  echo "No prompt under '$HEADING' in docs/SCHEDULED_TASKS.md." >&2
  exit 2
fi

LOG="state/logs/claude-$1-$(date -u +%Y%m%dT%H%M%SZ).log"
echo "$(date -u +%FT%TZ) starting $1 session; transcript in $LOG"
# Auto mode lets an unattended run proceed without prompts; the repo's
# PreToolUse hook still denies broker order tools. No MCP servers are loaded,
# so the session has web search and the local CLI, not account connectors.
status=0
claude -p "$PROMPT" --permission-mode auto --strict-mcp-config >"$LOG" 2>&1 || status=$?
echo "$(date -u +%FT%TZ) finished $1 session with exit $status"
exit "$status"
