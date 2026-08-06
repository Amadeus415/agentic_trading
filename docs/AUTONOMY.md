# Autonomous portfolio operations

Edgecraft runs a market-weekday, long-only equity-and-crypto-equity paper mandate without
routine human approval. Autonomy is split across two trust domains:

```text
Codex Scheduled wakeup
  → Edgecraft due/idempotency/budget check
  → completed-session intelligence across the full mandate universe
  → focused Browserbase + public-source context for ranked candidates
  → Codex read-only Robinhood observation, final quote refresh, and structured recommendation
  → Edgecraft policy + freshness + cash + concentration + tilt gate
   → paper portfolio update + paper_trade_recorded audit event
   → shadow complete
      (manual live operation remains outside the scheduled path):
  → Codex read-only execution preflight + Robinhood review
  → Edgecraft market-session + spread + liquidity + drawdown + turnover gate
  → policy fingerprint re-check
  → one expiring permit per order
  → PreToolUse permit claim
  → Robinhood placement
  → order/position reconciliation + audit
```

Codex owns reasoning and the authenticated MCP session. Edgecraft owns
authority. A model cannot make the daily paper budget larger, add a symbol, weaken a
limit, disable review, mint a permit, reuse a permit, or clear the kill switch.
See [the external-context guide](EXTERNAL_CONTEXT.md) for provider setup,
freshness requirements, and the untrusted-content boundary.
See [the decision data model](DECISION_DATA_MODEL.md) for the exact immutable
record written for every valid decision attempt.

## Start with the supplied $2 daily paper mandate

```bash
uv sync --extra dev

export BROWSERBASE_API_KEY='your-free-project-key'

edgecraft health --real-data-symbol SPY
edgecraft mandate-validate --config examples/mandate.index-dca.json

edgecraft cycle \
  --mandate examples/mandate.index-dca.json \
  --ledger state/edgecraft-paper.db \
  --force
```

`--force` bypasses schedule timing only. It does not bypass the daily budget,
policy, account eligibility, quote freshness, open-order, cash, concentration,
review, permit, or kill-switch checks.

The supplied mandate is:

- shadow-only;
- $2 per market weekday, with no rollover;
- long-only selection across a curated daily set of liquid stocks, ETFs, and
  crypto-equity vehicles such as IBIT, ETHA, COIN, and MSTR, drawn from
  `examples/universe.broad-equity-crypto.json`;
- strategic baseline weights that include core index sleeves plus crypto ETF
  sleeves (not equal-weight across the full opportunity set);
- balanced risk, allowing at most a 15 percentage-point tactical tilt;
- every weekday at 10:00 America/New_York;
- free to paper trade less than $2 or hold all simulated cash;
- unable to sell, use leverage, trade options, place native coin orders, or leave
  the whitelist.

Native cryptocurrency coins are outside Robinhood Agentic equity placement.
Crypto exposure is only through equity-listed vehicles the owner put on the
whitelist.

## Unattended scheduling

Use a Codex Scheduled task as the single wake-up mechanism. Follow
[the scheduled-task operating guide](CODEX_SCHEDULED_TASK.md) and keep the task
in the local checkout so it shares the durable ledger and kill switch. Wakeups
before the configured time return `not_due`; repeated wakeups return the same
idempotent run without invoking the model again.

The Mac must be on, the user session available, Codex authenticated, and
Robinhood MCP OAuth current for read-only account observations. Schedule only
`./scripts/run_scheduled_cycle.sh` (or `make scheduled-cycle`); the script is
fixed to the daily shadow mandate and dedicated `state/edgecraft-paper.db`
ledger, and cannot be redirected to live trading.

A side-effect-free transient failure retries in-process on the same wake up to
the existing attempt budget (initial attempt plus three automatic retries). Any
permit issuance or placement aborts further auto-retry. An operator may authorize
up to four additional audited attempts with `--retry-side-effect-free "reason"`,
but only when the ledger proves there was no broker side effect, the kill switch
is inactive, no order is unresolved, and no order was placed that day. A permit
that was claimed or could have reached the broker is never retryable. A permit
that was revoked before claim is retryable only when a matching terminal
rejection records zero fill and no broker order identity.

On each live `cycle`, if the ledger still has unresolved placed-order keys from
a prior run, Edgecraft re-reconciles or recovers each order before new
observe/proposal work. Proven filled/rejected/canceled events clear those keys;
non-terminal state keeps the halt, blocks new risk approval, and records audit
events.

Each retry receives new proposal and order identities while retaining the same
idempotent daily run. The first immutable performance observation for that run
is reused, so a retry cannot double-count the day's contribution or rewrite the
benchmark record.

## Risk settings

`risk_level` changes only the default maximum tactical contribution tilt:

| Setting | Default max tilt |
| --- | ---: |
| conservative | 5 percentage points |
| balanced | 15 percentage points |
| aggressive | 30 percentage points |

Hard policy remains independent. “Aggressive” cannot enable a new symbol,
exceed the budget, spend unavailable cash, violate concentration, accept stale
data, trade an unapproved session or illiquid quote, exceed turnover/drawdown,
sell when disabled, or use options/margin. Override `max_tactical_tilt`
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
2. Keep the universe broad, liquid, and fractionally tradable. The default
   catalog mixes equities, sector/theme ETFs, and crypto-equity vehicles (see
   `examples/universe.broad-equity-crypto.json`). Set the first live budget and
   daily notional to the same tiny amount.
3. Copy `examples/mandate.index-dca-live.example.json` and
   `examples/policy.autonomous-live.example.json`.
4. Review both files. Set the live mandate's `enabled` to `true` only after the
   account owner accepts the exact capital, universe, schedule, and limits.
5. Validate, register, and run once:

```bash
edgecraft mandate-validate --config path/to/live-mandate.json
edgecraft mandate-register \
  --config path/to/live-mandate.json \
  --ledger state/edgecraft-paper.db
edgecraft cycle \
  --mandate path/to/live-mandate.json \
  --ledger state/edgecraft-paper.db \
  --force
```

6. Confirm the broker order and ledger reconcile. Then enable its Codex Scheduled task.

Do not reuse the shadow mandate ID for a materially different policy. A live
placement receives one opaque permit per order, valid for at most five minutes.
The project hook denies placement without it, on input mismatch, after expiry,
after reuse, or while halted. The guard covers direct Robinhood MCP calls and
the nested `exec` tool path used by current Codex runtimes; nested placement is
accepted only as one flat literal call whose account, symbol, side, amount,
order type, time in force, and market-hours scope match the permit exactly.

## Monitoring and incident response

```bash
edgecraft runs --ledger state/edgecraft-paper.db
edgecraft ledger --path state/edgecraft-paper.db
edgecraft autonomy-health --ledger state/edgecraft-paper.db
edgecraft metrics --ledger state/edgecraft-paper.db --format prometheus
```

CLI surfaces are `edgecraft autonomy-health` and `edgecraft metrics`. Telemetry
contains run IDs, statuses, counts, symbols, and notional summaries but not
account IDs, account numbers, tokens, or raw broker/model payloads.

Every proposal is persisted before authority and includes the full structured
decision reasoning: confidence, hypothesis, evidence, alternatives considered,
risks, data sources, cited context IDs, and per-symbol allocation rationale.
Placed and terminal order events retain that immutable reasoning snapshot next
to the broker state, notional, fill amount, and average fill price. This makes a
trade explainable even when later model output or external context changes. The
ledger adds this canonical reasoning from the stored proposal for every trade
event recorded by the autonomous execution and reconciliation path;
callers cannot omit or replace it.

Before proposal creation, Edgecraft also writes a content-hashed decision packet
containing the complete normalized mandate, risk policy, research evidence,
Browserbase/SEC/social context, completed-session market intelligence, broker
portfolio snapshot, quotes, material
evidence inventory, and structured model judgment. Every decision needs recorded
evidence, and invest decisions fail closed unless each allocation cites it. Inspect a packet with
`edgecraft decision --ledger state/edgecraft-paper.db --run-id RUN_ID`.

If the execution agent reaches the broker but returns malformed or otherwise
invalid structured output, Edgecraft performs one read-only recovery lookup for
the exact account, symbol, side, amount, order type, and authority time window.
It records an unambiguous terminal broker result and never retries placement. An
exact filled, rejected, or canceled result can finish automatically. Missing,
partial, non-terminal, or ambiguous broker truth remains fail-closed and turns
on the kill switch.

Emergency stop:

```bash
edgecraft halt \
  --ledger state/edgecraft-paper.db \
  --reason "unexpected order or reconciliation mismatch"
```

Halting revokes every unclaimed permit. Edgecraft also halts automatically
after a non-terminal `placed` order, partial fill, unknown broker state,
execution identity mismatch, or an exception after live authority was issued.
A run that only reaches `placed` is marked `failed` (never `completed`) and
leaves `unresolved_order_keys` until a true terminal broker event is recorded.
The next live cycle re-reconciles those keys autonomously; when every unresolved
order reaches a terminal broker state, the automatic halt is cleared. Manual
`incident-reconcile` remains for ambiguous recovery where the operator records
terminal events independently. `incident-reconcile` accepts only failed runs
whose every order already has a coherent terminal event. Before a manual resume
when the monitor cannot clear state, reconcile Robinhood orders, positions,
buying power, and the Edgecraft ledger:

```bash
edgecraft incident-reconcile \
  --ledger state/edgecraft-paper.db \
  --run-id RUN_ID \
  --reason "exact broker order, position, and cash independently verified"
edgecraft resume \
  --ledger state/edgecraft-paper.db \
  --reason "broker state reconciled and incident resolved"
```

`incident-reconcile` only accepts a failed run whose every proposed order has
one coherent terminal event. It does not clear the kill switch; resumption is a
separate, explicit control action.

The agent, SPY benchmark, and fixed strategic shadow books advance on every due
cycle with identical contributions and cost assumptions. Inspect them with
`edgecraft performance --ledger state/edgecraft-paper.db --mandate-id MANDATE_ID`.
See [the performance guide](PERFORMANCE_EVALUATION.md) for interpretation.

## Validation boundary

Repository validation includes unit/integration tests for schedule timing,
budget accounting, confidence/tilt limits, quote/account freshness, duplicate
cycles, retries, permit mismatch/reuse/kill behavior, simulated fills,
readiness, and metrics. It also includes current Yahoo
market data, authenticated Robinhood account discovery, full read-only account
and market observations, and unattended shadow proposals.

No real order is placed by the test suite or normal shadow validation. A real
trade occurs only from an enabled live mandate plus a trading-enabled policy,
fresh eligible Agentic account state, an approved proposal, a successful
Robinhood review, and a claimed Edgecraft permit.
