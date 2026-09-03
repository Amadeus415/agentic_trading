#!/usr/bin/env bash
# Install the code-only monitor as a per-user macOS LaunchAgent at minute 7.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.edgecraft.paper-monitor"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST="${PLIST_DIR}/${LABEL}.plist"
LOG_DIR="${ROOT}/state/logs"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

mkdir -p "$PLIST_DIR" "$LOG_DIR"
plutil -create xml1 "$TMP"
/usr/libexec/PlistBuddy -c "Add :Label string ${LABEL}" "$TMP"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments array" "$TMP"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:0 string /bin/bash" "$TMP"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:1 string ${ROOT}/scripts/run_local_monitor.sh" "$TMP"
/usr/libexec/PlistBuddy -c "Add :WorkingDirectory string ${ROOT}" "$TMP"
/usr/libexec/PlistBuddy -c "Add :StartCalendarInterval dict" "$TMP"
/usr/libexec/PlistBuddy -c "Add :StartCalendarInterval:Minute integer 7" "$TMP"
/usr/libexec/PlistBuddy -c "Add :ProcessType string Background" "$TMP"
/usr/libexec/PlistBuddy -c "Add :StandardOutPath string ${LOG_DIR}/monitor.log" "$TMP"
/usr/libexec/PlistBuddy -c "Add :StandardErrorPath string ${LOG_DIR}/monitor.error.log" "$TMP"
plutil -lint "$TMP"
mv "$TMP" "$PLIST"

launchctl bootout "gui/${UID}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${UID}" "$PLIST"
launchctl enable "gui/${UID}/${LABEL}"
launchctl print "gui/${UID}/${LABEL}" >/dev/null
echo "Installed ${LABEL}; the next code-only monitor runs at minute 7."
