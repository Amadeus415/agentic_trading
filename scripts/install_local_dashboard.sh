#!/usr/bin/env bash
# Keep the read-only dashboard available on this Mac, bound to localhost only.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.edgecraft.dashboard"
NODE_BIN="$(command -v node)"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

if [[ ! -f "$ROOT/dashboard/.next/BUILD_ID" ]]; then
  echo 'Build dashboard first: cd dashboard && npm ci && npm run build' >&2
  exit 2
fi
mkdir -p "$(dirname "$PLIST")" "$ROOT/state/logs"
plutil -create xml1 "$TMP"
/usr/libexec/PlistBuddy -c "Add :Label string ${LABEL}" "$TMP"
/usr/libexec/PlistBuddy -c 'Add :ProgramArguments array' "$TMP"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:0 string ${NODE_BIN}" "$TMP"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:1 string ${ROOT}/dashboard/node_modules/next/dist/bin/next" "$TMP"
/usr/libexec/PlistBuddy -c 'Add :ProgramArguments:2 string start' "$TMP"
/usr/libexec/PlistBuddy -c 'Add :ProgramArguments:3 string --hostname' "$TMP"
/usr/libexec/PlistBuddy -c 'Add :ProgramArguments:4 string 127.0.0.1' "$TMP"
/usr/libexec/PlistBuddy -c 'Add :ProgramArguments:5 string --port' "$TMP"
/usr/libexec/PlistBuddy -c 'Add :ProgramArguments:6 string 3000' "$TMP"
/usr/libexec/PlistBuddy -c "Add :WorkingDirectory string ${ROOT}/dashboard" "$TMP"
/usr/libexec/PlistBuddy -c 'Add :EnvironmentVariables dict' "$TMP"
/usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:EDGECRAFT_FUND_DB string ${ROOT}/state/edgecraft-aggressive.db" "$TMP"
/usr/libexec/PlistBuddy -c 'Add :RunAtLoad bool true' "$TMP"
/usr/libexec/PlistBuddy -c 'Add :KeepAlive bool true' "$TMP"
/usr/libexec/PlistBuddy -c 'Add :ThrottleInterval integer 10' "$TMP"
/usr/libexec/PlistBuddy -c "Add :StandardOutPath string ${ROOT}/state/logs/dashboard.log" "$TMP"
/usr/libexec/PlistBuddy -c "Add :StandardErrorPath string ${ROOT}/state/logs/dashboard.error.log" "$TMP"
plutil -lint "$TMP"
mv "$TMP" "$PLIST"
launchctl bootout "gui/${UID}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${UID}" "$PLIST"
launchctl enable "gui/${UID}/${LABEL}"
echo 'Installed read-only dashboard at http://127.0.0.1:3000.'
