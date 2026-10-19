#!/usr/bin/env bash
# Install the Claude Code research and weekly review sessions as per-user
# macOS LaunchAgents. Times are local (Pacific). launchd runs one missed
# session after sleep; the cycle key stops it from repeating a finished one.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_DIR="${HOME}/Library/LaunchAgents"
LOG_DIR="${ROOT}/state/logs"
CLAUDE_BIN="$(command -v claude)" || { echo "claude CLI not found on PATH." >&2; exit 2; }
# launchd starts with a bare PATH; give sessions the tools they call.
TASK_PATH="$(dirname "$CLAUDE_BIN"):$(dirname "$(command -v uv)"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CONFIG_DIR="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}"

install_agent() {
  local task="$1" label="com.edgecraft.claude-$1" schedule="$2"
  local plist="${PLIST_DIR}/${label}.plist" tmp
  tmp="$(mktemp)"
  plutil -create xml1 "$tmp"
  /usr/libexec/PlistBuddy -c "Add :Label string ${label}" "$tmp"
  /usr/libexec/PlistBuddy -c "Add :ProgramArguments array" "$tmp"
  /usr/libexec/PlistBuddy -c "Add :ProgramArguments:0 string /bin/bash" "$tmp"
  /usr/libexec/PlistBuddy -c "Add :ProgramArguments:1 string ${ROOT}/scripts/run_claude_task.sh" "$tmp"
  /usr/libexec/PlistBuddy -c "Add :ProgramArguments:2 string ${task}" "$tmp"
  /usr/libexec/PlistBuddy -c "Add :WorkingDirectory string ${ROOT}" "$tmp"
  /usr/libexec/PlistBuddy -c "Add :EnvironmentVariables dict" "$tmp"
  /usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:PATH string ${TASK_PATH}" "$tmp"
  /usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:CLAUDE_CONFIG_DIR string ${CONFIG_DIR}" "$tmp"
  /usr/libexec/PlistBuddy -c "Add :StartCalendarInterval array" "$tmp"
  local i=0 entry weekday hour minute
  for entry in $schedule; do
    IFS=: read -r weekday hour minute <<<"$entry"
    /usr/libexec/PlistBuddy -c "Add :StartCalendarInterval:${i} dict" "$tmp"
    if [[ "$weekday" != "-" ]]; then
      /usr/libexec/PlistBuddy -c "Add :StartCalendarInterval:${i}:Weekday integer ${weekday}" "$tmp"
    fi
    /usr/libexec/PlistBuddy -c "Add :StartCalendarInterval:${i}:Hour integer $((10#$hour))" "$tmp"
    /usr/libexec/PlistBuddy -c "Add :StartCalendarInterval:${i}:Minute integer $((10#$minute))" "$tmp"
    i=$((i + 1))
  done
  /usr/libexec/PlistBuddy -c "Add :ProcessType string Background" "$tmp"
  /usr/libexec/PlistBuddy -c "Add :StandardOutPath string ${LOG_DIR}/claude-${task}.log" "$tmp"
  /usr/libexec/PlistBuddy -c "Add :StandardErrorPath string ${LOG_DIR}/claude-${task}.error.log" "$tmp"
  plutil -lint "$tmp" >/dev/null
  mv "$tmp" "$plist"

  launchctl bootout "gui/${UID}/${label}" 2>/dev/null || true
  launchctl bootstrap "gui/${UID}" "$plist"
  launchctl enable "gui/${UID}/${label}"
  launchctl print "gui/${UID}/${label}" >/dev/null
  echo "Installed ${label}."
}

mkdir -p "$PLIST_DIR" "$LOG_DIR"
# weekday:hour:minute, weekday 0 = Sunday, - = every day.
install_agent research "-:07:15 -:10:15 -:12:15 -:18:15"
install_agent review "0:17:15"
