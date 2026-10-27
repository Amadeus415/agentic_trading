#!/usr/bin/env bash
# Run the benchmark on this Mac with launchd:
#   com.nightshift.session  four agent sessions a day (00:15, 06:15, 12:15, 18:15 local)
#   com.nightshift.tick     settle, mark, trade baselines, publish the site, every 15 minutes
# Sessions run only while the Mac is awake; launchd runs one missed session after sleep.
# Run it from the checkout the benchmark should use. NIGHTSHIFT_HOME defaults to ./var.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${NIGHTSHIFT_HOME:-${ROOT}/var}"
BIN="${ROOT}/.venv/bin/nightshift"
CLAUDE_BIN="$(command -v claude)" || { echo "claude CLI not found on PATH." >&2; exit 2; }
[[ -x "$BIN" ]] || { echo "Run 'make install' first." >&2; exit 2; }
PLIST_DIR="${HOME}/Library/LaunchAgents"
TASK_PATH="${ROOT}/.venv/bin:$(dirname "$CLAUDE_BIN"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "$PLIST_DIR" "${HOME_DIR}/logs"

install_agent() {
  local label="com.nightshift.$1" command="$2" when="$3"
  local plist="${PLIST_DIR}/${label}.plist"
  cat >"$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${label}</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>-c</string><string>${command}</string></array>
  <key>WorkingDirectory</key><string>${ROOT}</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>${TASK_PATH}</string>
    <key>NIGHTSHIFT_HOME</key><string>${HOME_DIR}</string>
    <key>CLAUDE_CONFIG_DIR</key><string>${CLAUDE_CONFIG_DIR:-${HOME}/.claude}</string>
  </dict>
  ${when}
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>${HOME_DIR}/logs/$1.log</string>
  <key>StandardErrorPath</key><string>${HOME_DIR}/logs/$1.log</string>
</dict></plist>
PLIST
  plutil -lint "$plist" >/dev/null
  launchctl bootout "gui/${UID}/${label}" 2>/dev/null || true
  launchctl bootstrap "gui/${UID}" "$plist"
  echo "Installed ${label}."
}

times=""
for hour in 0 6 12 18; do
  times+="<dict><key>Hour</key><integer>${hour}</integer><key>Minute</key><integer>15</integer></dict>"
done
install_agent session "'${BIN}' session" "<key>StartCalendarInterval</key><array>${times}</array>"
install_agent tick "'${BIN}' tick && '${BIN}' publish" "<key>StartInterval</key><integer>900</integer><key>RunAtLoad</key><true/>"
