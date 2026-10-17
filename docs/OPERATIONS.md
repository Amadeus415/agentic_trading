# Local operation and explicit v2 cutover

Development source is `agentic_trading/`; authoritative private state is in the sibling `agentic_trading_runtime/`. Use only a clean runtime on `main` for operation. Source changes and Git pushes do not deploy it. This rebuild leaves the runtime checkout and its ledger untouched; validation uses a private copy.

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
```

Preparation initializes/reopens v2 using the new default config and shared database; it does not retire v1 implicitly. `fund-retire` refuses open inventory and appends a retirement event once. If v1 has positions, stop the cutover and manage them under its existing mandate before retirement. Never force-close at invented marks or remove trades. Old accepted requests remain replayable, but new accounting cycles on a retired fund are rejected.

The v2 initial deposit is independent experimental capital. It does not increase v1 NAV or reset its losses. The default database filename remains `state/edgecraft-aggressive.db`, containing both fund IDs. The development ledger is older and cannot establish current operational state.

## Schedules and monitoring

Update saved trading prompts to the durable v2 prompt in [CODEX_SCHEDULED_TASK.md](CODEX_SCHEDULED_TASK.md) and evolution prompts to the new config before resuming. Keep the existing cadence unless deliberately changing it; equity-session names now identify research windows. Do not resume until both public venues, required sources, and position marks work with normal TLS verification. A certificate, access, or integrity failure is an operating blocker, not a cash-hold decision.

The installed monitor runs `scripts/run_local_monitor.sh` every five minutes. The new source points it at v2; the old runtime monitor continues running old source until deployment/reinstallation. It refuses partial action if any open-position mark fails, applies mechanical exits or settlement, verifies, then refreshes reports. A cash-only monitor need not add a cycle.

Research uses subscription-backed Codex; the monitor is local Python. The Mac and app must be available for local scheduled tasks ([official documentation](https://learn.chatgpt.com/docs/automations?surface=app)). Check saved automation and LaunchAgent state directly; documentation does not prove installation.

## Dashboard and reports

```bash
make fund-report-file
make fund-lineage
make fund-show
make fund-verify
cd dashboard && npm run dev
```

The fund selector scopes overview, trades, cycles, brain, and attribution to the chosen fund. V2 is the default when initialized. Generate `state/fund-report-edgecraft-aggressive.json` for the archive; the current `state/fund-report.json` serves v2. The reader checks `fund_id` before accepting either report. `EDGECRAFT_FUND_DB` and `EDGECRAFT_FUND_REPORT` can override local paths; reports from another fund remain unavailable rather than mislabelled.

V2 scheduled chart output is `assets/prediction-progress.svg`; the v1 chart and its archived copy are retained. Publishing a public snapshot is a separate operator action. Never commit private databases, evidence packets, caches, or credentials.

## Release checks

```bash
make validate
cd dashboard && npm run lint && npm test && npm run build
EDGECRAFT_FUND_DB=/absolute/path/to/verified-copy.db node scripts/smoke-db.mjs
```

Verify the v1 fund before and after initializing v2 on a copy, compare all original cycle/event rows, and verify both funds. Live API checks are read-only and separate from fixture tests. If package installation encounters TLS problems, a complete cached installation can be validated offline; never disable certificate verification.
