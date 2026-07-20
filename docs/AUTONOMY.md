# Autonomous portfolio operations

Edgecraft can run a weekly, long-only index-fund mandate without routine human
approval. Autonomy is split across two trust domains:

```text
launchd wakeup
  → Edgecraft due/idempotency/budget check
  → Browserbase + public-source context collection and audit
  → Codex read-only Robinhood observation and structured recommendation
  → Edgecraft policy + freshness + cash + concentration + tilt gate
  → shadow complete
     or, only for an explicitly live mandate:
  → one expiring permit per order
  → Codex refresh + Robinhood review
  → PreToolUse permit claim
  → Robinhood placement
  → order/position reconciliation + audit
```

Codex owns reasoning and the authenticated MCP session. Edgecraft owns
authority. A model cannot make the weekly budget larger, add a symbol, weaken a
limit, disable review, mint a permit, reuse a permit, or clear the kill switch.
See [the external-context guide](EXTERNAL_CONTEXT.md) for provider setup,
freshness requirements, and the untrusted-content boundary.

## Start with the supplied $10 shadow mandate

```bash
uv sync --extra dev

export BROWSERBASE_API_KEY='your-free-project-key'

edgecraft health --real-data-symbol SPY
edgecraft mandate-validate --config examples/mandate.index-dca.json

edgecraft cycle \
  --mandate examples/mandate.index-dca.json \
  --ledger state/edgecraft.db \
  --force
```

`--force` bypasses schedule timing only. It does not bypass the weekly budget,
policy, account eligibility, quote freshness, open-order, cash, concentration,
review, permit, or kill-switch checks.

The supplied mandate is:

- shadow-only;
- $10 per ISO week;
- long-only VTI/VXUS/BND;
- 60/25/15 strategic weights;
- balanced risk, allowing at most a 15 percentage-point tactical tilt;
- Monday at 10:00 America/New_York;
- free to invest less than $10 or hold all cash;
- unable to sell, use leverage, trade options, or leave the whitelist.

## Unattended scheduling

On macOS:

```bash
edgecraft schedule-install \
  --mandate examples/mandate.index-dca.json \
  --ledger state/edgecraft.db \
  --interval-seconds 1800

edgecraft schedule-status --mandate-id index_dca
```

The launchd service wakes every 30 minutes and at login. Most wakeups are cheap:
before the scheduled weekly time they return `not_due`; after one run exists for
the ISO week they return the same run without invoking the model. Logs live in
ignored `state/scheduler/` files. Remove the service with:

```bash
edgecraft schedule-remove --mandate-id index_dca
```

The Mac must be on, the user session available, Codex authenticated, and
Robinhood MCP OAuth current. A side-effect-free transient failure may retry up
to three times. A run that issued any execution permit never retries
automatically.

## Risk settings

`risk_level` changes only the default maximum tactical contribution tilt:

| Setting | Default max tilt |
| --- | ---: |
| conservative | 5 percentage points |
| balanced | 15 percentage points |
| aggressive | 30 percentage points |

Hard policy remains independent. “Aggressive” cannot enable a new symbol,
exceed the budget, spend unavailable cash, violate concentration, accept stale
data, sell when disabled, or use options/margin. Override `max_tactical_tilt`
explicitly when a mandate needs a tighter limit.

## Shadow-to-live promotion

Live operation is a versioned policy decision, never a model decision.

Market-day mandates use one idempotency key and one budget per weekday. Exchange
holidays and unscheduled closures still resolve to a hold through fresh broker
tradability and market-state checks. A policy may waive Robinhood's per-order
preview only when the owner has explicitly granted standing unattended execution
authority and `standing_execution_authorization=true`; all Edgecraft cash,
symbol, concentration, freshness, permit, reconciliation, and kill-switch gates
remain mandatory.

1. Run repeated real-data shadow cycles and inspect proposals, holds, rejected
   decisions, quote freshness, and subsequent market prices.
2. Keep the universe broad, liquid, fractionally tradable ETFs. Set the first
   live budget and daily notional to the same tiny amount.
3. Copy `examples/mandate.index-dca-live.example.json` and
   `examples/policy.autonomous-live.example.json`.
4. Review both files. Set the live mandate's `enabled` to `true` only after the
   account owner accepts the exact capital, universe, schedule, and limits.
5. Validate, register, and run once:

```bash
edgecraft mandate-validate --config path/to/live-mandate.json
edgecraft mandate-register \
  --config path/to/live-mandate.json \
  --ledger state/edgecraft.db
edgecraft cycle \
  --mandate path/to/live-mandate.json \
  --ledger state/edgecraft.db \
  --force
```

6. Confirm the broker order and ledger reconcile. Then install its schedule.

Do not reuse the shadow mandate ID for a materially different policy. A live
placement receives one opaque permit per order, valid for at most five minutes.
The project hook denies placement without it, on input mismatch, after expiry,
after reuse, or while halted.

## Monitoring and incident response

```bash
edgecraft runs --ledger state/edgecraft.db
edgecraft ledger --path state/edgecraft.db
edgecraft autonomy-health --ledger state/edgecraft.db
edgecraft metrics --ledger state/edgecraft.db --format prometheus
```

FastAPI also exposes `GET /api/autonomy/health` and `GET /metrics`. Telemetry
contains run IDs, statuses, counts, symbols, and notional summaries but not
account IDs, account numbers, tokens, or raw broker/model payloads.

Emergency stop:

```bash
edgecraft halt \
  --ledger state/edgecraft.db \
  --reason "unexpected order or reconciliation mismatch"
```

Halting revokes every unclaimed permit. Edgecraft also halts automatically
after a partial fill, unknown broker state, execution identity mismatch, or an
exception after live authority was issued. Before resuming, reconcile
Robinhood orders, positions, buying power, and the Edgecraft ledger:

```bash
edgecraft resume \
  --ledger state/edgecraft.db \
  --reason "broker state reconciled and incident resolved"
```

## Validation boundary

Repository validation includes unit/integration tests for schedule timing,
budget accounting, confidence/tilt limits, quote/account freshness, duplicate
cycles, retries, permit mismatch/reuse/kill behavior, simulated fills,
readiness, metrics, and launchd generation. It also includes current Yahoo
market data, authenticated Robinhood account discovery, full read-only account
and market observations, and unattended shadow proposals.

No real order is placed by the test suite or normal shadow validation. A real
trade occurs only from an enabled live mandate plus a trading-enabled policy,
fresh eligible Agentic account state, an approved proposal, a successful
Robinhood review, and a claimed Edgecraft permit.
