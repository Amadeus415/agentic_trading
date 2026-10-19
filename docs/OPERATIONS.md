# Local operation and explicit v2 cutover

Development source is `agentic_trading/`; authoritative private state is in the sibling `agentic_trading_runtime/`. Use only a clean runtime on `main` for operation. Source changes and Git pushes do not deploy it. The v2 cutover was completed on October 17, 2026 after validation on a private copy. V1 history and its pre-cutover state backup are preserved. The procedure below documents future verification and recovery.

## Cut over once

Keep v1 trading/evolution automations paused while deploying. Stop the existing monitor LaunchAgent during the transition so it cannot race ledger changes. Preserve the whole private `state/` directory, including packets, marks, logs, reports, and SQLite sidecars; use SQLite's backup API for a consistent database copy rather than copying a live WAL database alone. Do not replace the ledger with the development copy.

After merging/pushing the tested source, from the runtime:

```bash
./scripts/prepare_local_runtime.sh --update
.venv/bin/edgecraft fund-verify --config examples/fund.mandate.aggressive.json
.venv/bin/edgecraft fund-report --config examples/fund.mandate.aggressive.json \
  --output state/fund-report-edgecraft-aggressive.json
.venv/bin/edgecraft fund-retire --config examples/fund.mandate.aggressive.json
.venv/bin/edgecraft fund-verify --config examples/fund.mandate.aggressive.json
make fund-init
make fund-verify
make fund-report-file
make fund-scan
./scripts/install_local_monitor.sh
./scripts/install_claude_tasks.sh
```

Preparation initializes/reopens v2 using the new default config and shared database; it does not retire v1 implicitly. `fund-retire` refuses open inventory and appends a retirement event once. If v1 has positions, stop the cutover and manage them under its existing mandate before retirement. Never force-close at invented marks or remove trades. Old accepted requests remain replayable, but new accounting cycles on a retired fund are rejected.

The v2 initial deposit is independent experimental capital. It does not increase v1 NAV or reset its losses. The default database filename remains `state/edgecraft-aggressive.db`, containing both fund IDs. The development ledger is older and cannot establish current operational state.

## Schedules and monitoring

Install the research and review LaunchAgents described in [SCHEDULED_TASKS.md](SCHEDULED_TASKS.md) before resuming. Keep the existing cadence unless deliberately changing it; equity-session names now identify research windows. Do not resume until both public venues, required sources, and position marks work with normal TLS verification. A certificate, access, or integrity failure is an operating blocker, not a cash-hold decision.

The installed monitor runs `scripts/run_local_monitor.sh` every five minutes. For both the research fund and the code-only `edgecraft-baseline` fund it verifies, enforces exits and settlements, and scores open forecasts. It then runs `fund-baseline`, which scans at most once per `baseline_interval_minutes` and writes a cycle only when it buys; a failed public listing skips that pass. It refuses partial action if any open-position mark fails, verifies again, and refreshes `state/fund-report.json` and `state/fund-report-edgecraft-baseline.json`. The first run initializes the baseline fund's own one-time $1,000. A cash-only monitor need not add a cycle.

Research runs as headless Claude Code sessions and the monitor as local Python, both from LaunchAgents. The Mac must be awake for either to fire; no app needs to be open. Check `launchctl print gui/$UID/com.edgecraft.claude-research` and the `state/logs/claude-*` transcripts directly; documentation does not prove installation. The former Codex automations stay paused.

## Dashboard and reports

```bash
make fund-report-file
make fund-lineage
make fund-show
make fund-verify
cd dashboard && npm run dev
```

The fund selector scopes overview, trades, cycles, brain, and attribution to the chosen fund. V2 is the default when initialized. Generate `state/fund-report-edgecraft-aggressive.json` for the archive; `state/fund-report.json` serves v2 and the monitor writes `state/fund-report-edgecraft-baseline.json` for the control fund. The reader checks `fund_id` before accepting either report. `EDGECRAFT_FUND_DB` and `EDGECRAFT_FUND_REPORT` can override local paths; reports from another fund remain unavailable rather than mislabelled.

V2 scheduled chart output is `state/prediction-progress.svg` (gitignored so generated snapshots do not dirty the runtime); the v1 chart and its archived copy are retained. Publishing a public snapshot is a separate operator action. Never commit private databases, evidence packets, caches, or credentials.

## Release checks

```bash
make validate
cd dashboard && npm run lint && npm test && npm run build
EDGECRAFT_FUND_DB=/absolute/path/to/verified-copy.db node scripts/smoke-db.mjs
```

Verify the v1 fund before and after initializing v2 on a copy, compare all original cycle/event rows, and verify both funds. Live API checks are read-only and separate from fixture tests. If package installation encounters TLS problems, a complete cached installation can be validated offline; never disable certificate verification.

## Keep the local dashboard running

After installing locked dashboard dependencies and building in the runtime:

```bash
cd dashboard && npm ci && npm run build && cd ..
./scripts/install_local_dashboard.sh
launchctl print gui/$(id -u)/com.edgecraft.dashboard
```

The LaunchAgent serves the read-only dashboard at `http://127.0.0.1:3000`, binds only to localhost, and restarts it after failure or login. It uses an absolute Node executable and the authoritative runtime database. Logs stay in `state/logs/`. Rebuild and reinstall the agent after dashboard dependency/source updates.
