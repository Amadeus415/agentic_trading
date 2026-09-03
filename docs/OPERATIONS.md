# Local autonomous operation

Edgecraft runs from one clean local checkout. Codex Scheduled Tasks provide the
research model through the owner's ChatGPT subscription; the hourly monitor is
plain Python and uses no model. The Mac and Codex app must be running when a
task is due.

This is intentionally local. The source repository is public, while the ledger,
market-data cache, generated packets, and logs are private local state. No API
key, broker credential, or private state repository is needed.

## Runtime layout

Use the development checkout for coding and a sibling clone for unattended
operation:

```text
agentic_trading/          development checkout
agentic_trading_runtime/  clean main branch + private gitignored state
```

Every scheduled research task begins with:

```bash
./scripts/prepare_local_runtime.sh
```

That command refuses a dirty runtime, fast-forwards `main` from `origin`, syncs
the locked environment, verifies the ledger, and regenerates the canonical JSON
report. A push to `main` therefore reaches the autonomous fund on its next
scheduled run without deploying secrets.

## Cadences

| Loop | Scheduler | Model |
|:--|:--|:--|
| US open | Codex Scheduled Task, weekdays | subscription-backed Codex |
| US close | Codex Scheduled Task, weekdays | subscription-backed Codex |
| Off-hours | Codex Scheduled Task, Sunday | subscription-backed Codex |
| Monitor | macOS LaunchAgent, hourly at minute 7 | none |
| Evolution | Codex Scheduled Task, Sunday | subscription-backed Codex |

Trading tasks follow [CODEX_SCHEDULED_TASK.md](CODEX_SCHEDULED_TASK.md). Each
creates one packet and calls the fixed apply script once. A failed cycle key is
terminal and is never rewritten or retried.

The monitor calls `scripts/run_local_monitor.sh`. It verifies first, fetches all
open-position marks, refuses partial action if any fetch fails, applies
mechanical exits, verifies again, refreshes the report, and checks alerts.

The weekly evolution task writes one typed postmortem and calls `fund-evolve`
once. It may append evidence-gated playbook lifecycle events; it cannot modify
the mandate, accounting, paper-only boundary, or cash.

## Install or repair

From the clean runtime:

```bash
codex login status
./scripts/prepare_local_runtime.sh
./scripts/install_local_monitor.sh
launchctl print gui/$(id -u)/com.edgecraft.paper-monitor
```

`codex login status` should report ChatGPT login. Scheduled Tasks themselves are
created and inspected in the Codex app. Keep every task pointed at the runtime
checkout, not the development checkout.

## Health checks

```bash
make fund-show
make fund-verify
make fund-report-file
tail -n 100 state/logs/monitor.error.log
```

For a full source release check:

```bash
make validate
make security
cd dashboard && npm run lint && npm run build && node scripts/smoke-db.mjs
```

All fills are simulated. None of these commands contains a broker, wallet,
transfer, or real-order path.
