# Design of Edgecraft

Date: 2026-09-01. This document describes the system as it exists after
Phases 0–5 of [PLAN.md](PLAN.md). It is the map of how the paper fund works,
not a roadmap and not the accounting contract.

**One sentence:** the model researches beliefs inside versioned playbooks; code
owns quotes, size, stops, and whether a sleeve gets capital.

If you only remember one split: **`paper_fund.py` is the vault.** Everything
else is allowed to propose, size, mark, score, or evolve. Only
`PaperFundLedger.execute_cycle` can change cash, inventory, or the hash chain.

---

## How to read this

| If you want… | Read |
|---|---|
| Why the architecture changed | [PLAN.md](PLAN.md) §1–2 |
| Exact money formulas, packet schema, invariants | [FUND_ACCOUNTING.md](FUND_ACCOUNTING.md) |
| What the scheduled agent is told to do | [CODEX_SCHEDULED_TASK.md](CODEX_SCHEDULED_TASK.md) |
| How to run it off this laptop | [OPERATIONS.md](OPERATIONS.md) |
| How the live loops, types, and modules fit | this file |

Read §1–4 for the mental model. Read §5–11 when you need to follow a cycle
through code. Read §12–15 when you are changing something.

---

## 1. What this system is

Edgecraft is an autonomous **paper hedge fund**. It is capitalized once with
exactly $1,000 of fake money. Several times a weekday a model researches public
markets and writes a short-term (4–72 hour) falsifiable hypothesis. Deterministic
Python either turns that belief into a simulated fill or drops it. There is no
live mode, no broker adapter, and no path that can place, cancel, or mutate a
real order, account, transfer, or wallet.

The live book is `edgecraft-aggressive`
(`examples/fund.mandate.aggressive.json`, ledger
`state/edgecraft-aggressive.db`). It may hold several independent long/short
positions in stocks, native crypto, and binary prediction contracts. Options are
out of scope.

This is an engineering experiment. NAV movement on a short sample is not a
claim of skill. The machine’s job is to **keep score honestly** and to **stop
the model from being the trader**.

---

## 2. Authority: who owns what

The product rule is: **models propose, typed code authorizes.** After Phases
0–5 that split is finer than “the agent writes JSON, Python applies it.”

| Decision | Owner | Why |
|---|---|---|
| What to research, direction, mechanism, catalysts, falsifiers | Model | That is judgment over public evidence |
| `p_win`, target, stop, horizon, `playbook_id`, `driver` | Model | Beliefs must be stated so they can be sized and scored |
| Entry quantity | `sizing.py` | The model chose 1,000 YES shares at 34% confidence; Kelly would not |
| The price used to mark and fill | `marketdata/` | Packet quotes are advisory; a model must not pick its print |
| Whether a stop/target/horizon has hit | `monitor.py` | Stops that wait for the next session are not stops |
| Whether a sleeve may spend, and how much | `allocator.py` | Capital follows after-cost evidence, not last week’s narrative |
| Cash, inventory, fees, exposure, drawdown, idempotency | `paper_fund.py` | The vault. Never bypassed. |
| Fees, envelope, paper-only, accounting rules | Humans, checked in | Evolution is forbidden from touching these |
| Live broker / wallet / transfer | Nobody | `scripts/deny_broker_tools.py` is fail-closed |

Two consequences follow:

1. **A hold is valid.** Cash is a position. The model must still *research*;
   code may refuse to spend when after-cost expected value is below a threshold.
2. **The $100,000 / 58.5% dream is a human README fact.** It is stripped from
   `fund-context` so it cannot distort trade selection. A model told to hit
   100× in ten years will rationally buy lottery tickets.

---

## 3. Three loops, one ledger

There is still one SQLite book and one `execute_cycle`. Three cadences call it
(or only write events):

```text
SESSION (model on the hot path)
  fund-snapshot  →  model writes a belief packet  →  fund-run
       │                    │                           │
       │                    │              replace quotes from cache
       │                    │              size entries with Kelly
       │                    │              execute_cycle
       ▼                    ▼                           ▼
  state/marks/         JSON packet              append-only ledger

HOURLY (no model)
  monitor fetches marks → mechanical sell/cover → execute_cycle

WEEKLY (model optional, no cash)
  fund-report → postmortem JSON → validate → playbook_transition events
  allocator may freeze / retire / promote from the same evidence
```

Only the session loop calls a model to trade. The monitor is arithmetic over
open hypotheses. The evolution loop may propose typed diffs; it cannot change
cash.

That is the whole runtime. There is no second orchestrator, no second
accounting engine, and no hidden agent loop inside `paper_fund.py`.

---

## 4. The vault

`src/edgecraft/paper_fund.py` is both the domain model and the ledger.

### Storage

Three SQLite tables, append-only (triggers reject `UPDATE`/`DELETE`):

| Table | Role |
|---|---|
| `funds` | One-time capitalization. Mandate JSON is frozen at init. |
| `cycles` | The normalized decision, quotes, fills, settlements, resulting state, request digest |
| `events` | Hash-chained audit: `cycle_completed`, `cycle_rejected`, plus operational events |

`(fund_id, cycle_key)` is unique. Replaying the same payload is a no-op.
A different payload under a used key is rejected. A failed scheduled cycle key
is terminal: stop, keep the evidence, do not mutate the packet to pass a gate.

`fund-verify` replays every cycle from the original $1,000, recomputes
digests, and walks the event chain. If that is not green, nothing else matters.

### The only mutation

```text
PaperFundLedger.execute_cycle(decision, quotes, runtime=..., require_brain_journal=..., decision_audit=...)
```

On success it writes a `cycle_completed` event whose payload is the full
decision, quotes, fills, state, and audit sidecar — not a summary. On
validation failure it writes `cycle_rejected` with the exact packet and reason,
then raises. Either way the chain is complete.

Operational events (`alert_mark_fetch_failed`, `postmortem_completed`,
`playbook_transition`) go through `record_operational_event`. They do not move
money.

### What the vault still does, unchanged in spirit

- Signed positions: `+q` long, `-q` short. Sides are not interchangeable:
  `buy` cannot cover, `sell` cannot open a short, and so on.
- NAV = cash + Σ(q × mark). Gross / net / short exposure, turnover, concentration,
  drawdown are checked against the mandate envelope **after** sizing proposes
  quantities. Sizing cannot waive a cap.
- Fees (5 bps) and adverse slippage (10 bps) on every simulated fill, unless a
  displayed book is walked instead.
- Prediction contracts live in `[0, 1]`, settle only from a sourced `settled`
  quote of exactly `0` or `1`.
- Decimal money, UTC timestamps.

Formulas, side tables, and packet JSON live in
[FUND_ACCOUNTING.md](FUND_ACCOUNTING.md). Do not fork them here.

### What the vault grew, additively

These fields are optional so the 13 historical cycles still replay:

- `FundQuote.bids` / `asks` — displayed CLOB depth
- `FundOrder.quantity` may be `null`; belief fields (`p_win`, target, stop,
  playbook, driver, extra slippage, borrow)
- `FundHypothesis.p_win`, `playbook_id`, `driver`
- `FundPosition` / `FundFill` tags: `playbook_id`, `driver`, `opened_at`, borrow
- `CycleRuntimeMetadata`: token counts and `model_cost_usd`
- `CycleAuditRecord.sleeve_allocation` and `sizing`

Replay rule: **absent optional fields keep the old behavior.** No book → last
price plus mandate slippage. No `opened_at` → no invented borrow. Journal
gates that require `p_win` fire only when `require_brain_journal=True` on a
**new** apply.

---

## 5. The packet the model writes

A cycle input is:

```text
{
  "decision": FundDecision,
  "quotes":   [FundQuote, ...],
  "runtime":  { model, prompt_version, tokens, model_cost_usd }   // optional
}
```

`FundCyclePacket` is the strict subset emitted by the scheduled research task.
`fund-run` adds `edgecraft_version`, mandate digest, and input SHA-256.

### What a scheduled hypothesis must contain

On `--require-brain-journal` (always on for the scheduled script):

- a journal covering regime, opportunity set, intent, what changed, lessons
- one hypothesis per **open or ordered** instrument
- horizon ≤ 72 hours
- **`p_win`, `driver`, and `playbook_id`** — not merely `confidence`

`confidence` remains on the type so old packets replay. New scheduled packets
that only have `confidence` fail with
`scheduled hypotheses require p_win, driver, and playbook_id`.

An all-cash hold is legal when the journal exists. Flattening an open position
is a `sell` or `cover`, not a hold.

### Orders vs beliefs

The model’s job on an **entry** is: instrument, side (`buy`/`short`),
evidence, and a complete belief. Quantity may be `null`. On an **exit**,
quantity is inventory (the monitor always sets it; a session packet that
closes should too).

Sides stay exact. The vault will not infer “this buy is really a cover.”

---

## 6. One scheduled session, in order

This is the hot path. `scripts/run_scheduled_cycle.sh` is the only apply
script. It verifies, applies **once**, verifies, then redraws the README chart.

### 6.1 Context

`edgecraft fund-context` is what the model is allowed to see:

- current state (cash, positions, NAV, exposures)
- last 10 cycle summaries
- the **fund brain** (compact memory — §11)
- loaded playbooks and current sleeve weights
- the JSON schema and the rules list
- the mandate **minus** `growth_objective`

It does not see `$100,000`, `58.5%`, or any path to a broker.

### 6.2 Snapshot

`edgecraft fund-snapshot` fetches public marks for every open position (and any
`--instrument ID:asset_class` the researcher adds) and writes them under
`state/marks/`. This must happen **during research**, before `decision.as_of`
is frozen. Later apply will refuse to use a mark newer than `as_of`.

### 6.3 Research

The model scans every **active / incubating** playbook, writes one packet to
the path printed by `fund-cycle-key`
(`state/fund-inputs/YYYY-MM-DD-session-….json`), then calls the fixed apply
script exactly once.

UTC session slots (`schedule.py`), used by every scheduled task:

| UTC hours | Slot |
|---|---|
| 13–16 | `session-eu` |
| 16–20 | `session-us-open` |
| 20–23 | `session-us-close` |
| otherwise | `session-offhours` |

Cycle key is `{date}-{slot}`. Monitor keys are `monitor-{ISO timestamp}` so
they cannot collide.

### 6.4 Apply (`fund-run`)

The scheduled script always passes two flags that default **off** for replay:

```text
--require-brain-journal --code-owned-quotes --size-beliefs
```

`_fund_run` then does, in order:

1. Parse the packet.
2. **If `--code-owned-quotes`:** for each advisory quote, load
   `MarketDataRouter.latest_cached_quote(..., at_or_before=decision.as_of)`.
   If the packet price differs by more than 25 bps, **reject the cycle**.
   Replace the quote list with the cached marks (including book depth).
3. **If `--size-beliefs`:** build the attribution report (for calibration),
   allocate sleeves, run `size_decision`, **replace** `decision.orders`
   (and possibly `action`) with the sized result. Entry quantities from the
   model are ignored whenever a complete belief is present.
4. Idempotency / freshness / cycle-key / as-of-today checks.
5. `execute_cycle` — the vault. Risk envelope still applies.
6. `fund-verify`.

The CLI response includes `audit.code_owned_quotes` and `audit.sizing`
(`accepted` / `dropped`). The same objects are stored on the cycle sidecar
so next week can see *why* a belief did not become a fill.

If every entry is dropped, action becomes `HOLD`. That is the system working.

---

## 7. Code-owned quotes

`src/edgecraft/marketdata/__init__.py` is a small HTTPS failover list, not a
vendor SDK.

| Asset class | Providers, in order |
|---|---|
| crypto | Coinbase public ticker, then Binance |
| stock | Yahoo, then Stooq |
| prediction | Polymarket CLOB (price **and** bids/asks) |

Every successful fetch is cached as JSON on disk. Apply never hits the
network for the fill price; it reads the cache as-of the decision.

### Fill honesty, without breaking history

`_fill_price` in `paper_fund.py`:

1. Buy/cover with `asks` present → walk the book (quantity-weighted average,
   consuming displayed size). Insufficient depth is a validation error.
2. Sell/short with `bids` present → same, descending.
3. Otherwise → last price ± mandate slippage (every historical packet).
4. Then add `order.extra_slippage_bps` if set (monitor gap penalty: 20 bps).

So a 1,000-share Polymarket order against a thin book can no longer fill at
last price + 10 bps. Old cycles that never stored a book still replay at the
old model.

`fund-backfill-nav` can reconstruct a denser daily NAV from historical bars
**without writing the ledger**. Days without coverage keep the recorded mark
and disclose it. History is not rewritten.

---

## 8. Sizing: beliefs become quantity

`src/edgecraft/sizing.py` is the new money brain. It is a **pre-processor**.
It is not inside the accounting engine, because if Kelly lived in
`execute_cycle` you could not replay a cycle whose original quantity was 1,000
YES shares. The ledger stores what was *applied*; the sizer decides what to
offer on the scheduled path.

Constants (`SizingConfig`):

| Knob | Value | Role |
|---|---|---|
| Fractional Kelly | 0.25 | Don’t bet full Kelly on a miscalibrated model |
| Minimum after-cost edge | 2 bps | Don’t pay 15 bps round-trip for noise |
| Max driver weight | 40% of NAV | XLE long + QQQ short on one oil/rates story |
| Max prediction weight | 10% of NAV | Binaries must not dominate variance |
| Calibration minimum n | 5 | Don’t haircut on a toy sample |

### Per entry order

1. Stock while the cash session is closed → drop `market_closed_queued`.
2. `sell` / `cover` → use inventory. Never Kelly an exit.
3. Read `p_win`, target, stop from the order, else the journal hypothesis.
   Missing any of the three is a hard error.
4. **Calibration haircut.** If that `p_win` bucket (`50-60%`, …) has ≥ 5
   scored outcomes, replace `p_win` with `min(stated, realized win rate)`.
   With a handful of closed trades this almost never fires. It will start
   shrinking size as soon as the agent is measurably overconfident. The model
   is not asked to “be better calibrated”; the haircut does it.
5. **Edge gate.** After-cost expected return must clear 2 bps, using
   `fee_bps + 2 × slippage_bps` as the round-trip cost.

Linear (stock / crypto):

```text
upside   = |target − price| / price     # in the profitable direction
downside = |price − stop|   / price
E[r]     = p · upside − (1−p) · downside − costs
full Kelly f* = (b·p − q) / b           # b = upside/downside, q = 1−p
```

Binary (prediction):

```text
edge (buy YES)  = p − market_price
edge (short)    = market_price − p
E[r]            = edge − costs
full Kelly f*   = edge / (1 − price)    # buy YES
```

If `E[r]` is below 2 bps → drop `below_edge_threshold`.

6. Take `0.25 × f*`, then `min` of:
   - that weight
   - the playbook’s **sleeve weight** (incubating = 5% of NAV)
   - mandate `max_single_position_weight` (60% on the aggressive book)
   - 10% of NAV if prediction
   - remaining room under the 40% per-`driver` cap
7. `notional / price`, round down to the asset quantum (0.0001 stock,
   1 share prediction). Zero → drop.

A new stock short also gets `borrow_fee_bps_annual = 300`. Accrual happens
later in `execute_cycle` from `opened_at`. Historical positions have
`opened_at = None`, so replay does not invent borrow.

### Worked example (why this exists)

The old book bought 1,000 YES at $0.16 ($160, 16% of NAV) on a contract the
model itself scored at `p = 0.34`.

```text
edge        = 0.34 − 0.16 = 0.18
full Kelly  = 0.18 / 0.84 ≈ 21%
¼ Kelly     ≈ 5.4% of NAV
sleeve cap  = 5% (incubating)
prediction  = min(5.4%, 5%, 10%) = 5% → about $50, not $160
```

If instead `p = 0.40` at a market of `0.40`, edge after 25 bps of costs is
negative → the order never reaches the vault. That is the replacement for
“idle cash is rejected.”

---

## 9. The monitor: stops that do not wait for Codex

`src/edgecraft/monitor.py` builds a **normal** `FundDecision` with
`model="code-only-monitor"` and then calls the same `execute_cycle`. Every
mechanical exit is in the hash chain with a journal, a quote, and a digest.
Attribution can score `stop_hit` from real rows.

For each open position, using the latest journaled hypothesis and a
code-owned mark, it checks in order:

1. Quote status `settled` → leave the order list empty; the vault’s
   settlement path closes prediction contracts at 0 or 1.
2. Price through `invalidation_price` → `stop_hit`. If the print is *beyond*
   the stop (a gap), set `extra_slippage_bps = 20`.
3. Price through `target_price` → `target_hit`.
4. Elapsed hours since the hypothesis was first journaled ≥
   `expected_horizon_hours` → `horizon_expired`.
5. Stock and the cash session is closed → **queue**, do not fill overnight.

No hit → that position is left alone (the cycle may still be a hold that
refreshes marks).

Failed mark fetches do not silently skip. They append
`alert_mark_fetch_failed`. A book that cannot be marked is a known-blind
book, not a quietly optimistic NAV.

`--dry-run` prints the decision without applying.

---

## 10. Playbooks and sleeves

A playbook is two files, not a class hierarchy:

```text
playbooks/<id>/playbook.json    # typed PlaybookSpec
playbooks/<id>/prompt.md        # research instructions (hash recorded)
```

`PlaybookSpec` carries `id`, `version`, `thesis`, `universe`, `trigger`,
`entry_rule`, `exit_rule`, `sizing_hints`, `required_evidence_types`, and
`status`.

Statuses:

```text
proposed → validated → incubating → active
                 ↘ shadow          ↘ frozen → retired
```

Starting sleeves, all `incubating` (5% of NAV each):

| id | Intended edge |
|---|---|
| `resolution_arbitrage` | Near-expiry prediction contracts whose settlement is already determined by a public datum |
| `post_earnings_drift` | 1–3 day continuation after a large surprise and same-direction reaction |
| `crypto_momentum` | 24–72h continuation after a large liquid move with volume |
| `macro_reaction` | Scheduled data/policy events with a pre-written if/then; trade only on a consensus miss |

### Sleeves are tags, not books

There is still **one** cash balance. `playbook_id` is stored on orders, fills,
and positions. A position cannot change playbook mid-life. Sleeve NAV is a
derived cut in `fund-report`, not a second SQLite schema.

`allocator.allocate_sleeves(playbooks, round_trips)` is a pure function over
after-cost closed trades:

| Evidence | Capital |
|---|---|
| `shadow` | 0% — packets recorded, never filled |
| `incubating` | 5% of NAV |
| `active` and mean > 0 | share of `mean × √n`, capped at 40% per sleeve |
| n ≥ 20 and 95% lower bound > 0 (from incubating) | promote to `active` |
| n ≥ 30 and lower bound ≤ 0 | `frozen` → 0% |
| n ≥ 60 and lower bound ≤ 0 | `retired` → 0% |

New ideas start tiny. Losers lose the right to capital without a human
rewriting a prompt. That is the multi-armed bandit, implemented as arithmetic.

Weights are written into each cycle’s audit sidecar at apply time, so the
allocation that *sized this cycle* is immutable even if next week’s weights
differ.

---

## 11. Two memories: the brain and the report

These are easy to confuse. They answer different questions.

### Fund brain (`fund_brain.py`) — what the next model sees

A compact, deterministic summary of the ledger:

- last ~8 cycles: thesis, what changed, ending NAV, fill count, fees, and
  **next-cycle NAV change labeled as not causal**
- per-instrument: current qty, unrealized, realized exits, latest hypothesis
- recent rejections
- activity (cash weight, consecutive all-cash holds)
- adaptive prompts (now: scan playbooks, state `p_win`, do not manufacture
  a trade)

This is **decision memory**, not performance truth. It used to be the only
feedback loop. That is why the fund could not tell whether it had an edge.

### Attribution (`attribution.py`) — the scorekeeper

Read-only. It never invents a price the ledger did not store. For every
journaled hypothesis it walks later quotes and fills and records the **first**
terminal event:

`target_hit` | `stop_hit` | `manually_closed` | `expired` | `open`

Win = target hit, or a closing fill with positive realized P&L. Calibration is
stated `p_win` bucket vs realized win rate. Round trips get after-cost
expectancy, a bootstrap 95% interval, Sharpe from cycle-to-cycle NAV, and
cuts by asset class, side, session slot, horizon, **model**, and **playbook**.

Two counterfactuals in the same report:

- SPY buy-and-hold over the same window (when marks exist)
- “same instruments, same direction, always 5% of NAV” — separates
  **selection** from **sizing luck**

`list_full_cycles` returns the audit sidecar, including runtime (model,
tokens, cost). That used to come back empty even when the packet had it.
Without it you cannot compare models or notice that tokens cost more than the
book earns.

Graduation flags (200 closed trades, expectancy CI > 0, Sharpe > 1,
calibration error < 10 points, model cost < 20% of gross profit) are computed
here. They are currently false. That is the honest Phase 0 answer: **after
cost, this book does not yet have an edge**, and the machine can say so from
the same ledger it trades.

`edgecraft fund-report` prints this. The dashboard Attribution page renders
it next to NAV. Neither is a second accounting engine.

---

## 12. Evolution, gated by the research lab

`src/edgecraft/evolution.py` accepts a typed `Postmortem`:

```text
what_worked, what_failed, calibration_gaps, suspected_mechanism_failures
proposals: [ChangeProposal, ...]
```

`ChangeKind` is a closed enum:

`new_playbook` | `playbook_param` | `retire_playbook` | `research_prompt_edit` | `universe_edit`

A proposal whose `patch` keys touch `mandate`, `accounting`, `fee_bps`,
`slippage_bps`, `paper_only`, `risk_envelope`, or `broker` is rejected at
parse time. The vault is not a pull request.

Validation:

| Kind | Gate |
|---|---|
| `retire_playbook` | Always eligible (reduces risk) |
| `playbook_param`, `universe_edit` | Must be backtestable, with walk-forward artifacts: OOS return > 0 **and** deflated Sharpe probability ≥ 0.95 |
| `research_prompt_edit` (not backtestable) | Eligible only for a **shadow** sleeve |

The existing lab — `engine.py`, `walkforward.py`, CSCV / bootstrap in
`metrics.py` — is the gate. It is **not** the live book. A strategy that
looks good on synthetic bars still has to earn incubation capital in the
paper ledger.

`apply_postmortem` does not silently rewrite `playbooks/*.json` as policy.
It appends `postmortem_completed` and `playbook_transition` events.
`reconcile_allocator_lifecycle` writes `active` / `frozen` / `retired` when
the evidence thresholds trip.

A human can veto by deleting a playbook file. No human action is required
for the loop to run.

---

## 13. What the model is allowed to see — and what we took away

`fund-context` plus the starting / scheduled prompts are the entire
operating surface.

Removed from that surface (they used to push lottery tickets and churn):

- “idle cash is rejected”
- “default to a trade”
- “a week of holds is a process miss”
- `$100,000` and `58.5%` annualized

Replaced with: scan every playbook, submit every belief that clears cost
after the calibration haircut, state `p_win`, let code size. Uncertainty is
not a hold reason — quantify it. U.S. equity close is not a reason to stop
scanning crypto and prediction markets.

`growth.py` still exists for human visualization of the dream. It is not on
the trading path.

---

## 14. Replay, flags, and why the 13 old cycles still verify

`--code-owned-quotes` and `--size-beliefs` default **off**. Tests and
`fund-verify` call `execute_cycle` as a pure function of
`(decision, quotes, prior state)`. They do not need a network.

The 13 live cycles were the **old regime**: agent-chosen quantities, last
price plus 10 bps, no `p_win`/`playbook_id` required, stops only when a
session happened to run. `fund-report` will keep scoring them, but they
are not a verdict on Kelly, sleeves, or the monitor. The next scheduled
cycle with the two flags on is the first sample of *this* design.

Schema evolution is additive optional fields plus journal gates that only
run on new scheduled applies. That constraint is in `AGENTS.md` and it was
kept.

---

## 15. Operations shape

Local equivalents of the three loops:

```text
make fund-context
uv run edgecraft fund-snapshot --config ... --ledger ...
./scripts/run_scheduled_cycle.sh
make fund-monitor
make fund-report
make fund-alerts
```

Production is a clean local clone on `main`. Subscription-backed Codex Scheduled
Tasks run session research and weekly evolution; a macOS LaunchAgent runs the
model-free hourly monitor. `prepare_local_runtime.sh` fast-forwards from
`origin/main` before research, so a push becomes active at the next run. The
ledger, cached marks, generated packets, and logs remain gitignored local state.

`fund-alerts` covers chain failure, accounting failure, 15% / 30%
drawdown, `cycle_rejected` in the last 24h, and `alert_mark_fetch_failed`.
Optional Slack-compatible HTTPS webhook.

Setup: [OPERATIONS.md](OPERATIONS.md).

The dashboard (`dashboard/`) is a read-only Next.js view over the same
ledger: Overview, Trades, Attribution, Cycles, Brain. It must not grow a
second book.

`scripts/deny_broker_tools.py` is a fail-closed PreToolUse guard. Do not
loosen it for the paper fund.

---

## 16. Module map, in the order to read the code

Paper-fund path only. The research-lab modules (`engine.py`, `strategies.py`,
`walkforward.py`, `metrics.py`, `data.py`, `indicators.py`) are the
validation gate in §12, not the live trader.

| File | What it is |
|---|---|
| `paper_fund.py` | Types, envelope, fills, hash-chained SQLite. Start here. |
| `cli.py` | Wires flags to the pre-processors, then calls the vault. `_fund_run` is the session spine. |
| `schedule.py` | UTC slots and cycle keys. Tiny; read it once. |
| `marketdata/__init__.py` | Public quote providers + disk cache. |
| `sizing.py` | Belief → quantity. Pure. |
| `monitor.py` | Hypothesis + mark → mechanical `FundDecision`. |
| `playbooks.py` | Load `playbooks/*/playbook.json` + prompt hash. |
| `allocator.py` | After-cost round trips → sleeve weights. |
| `attribution.py` | Ledger → expectancy, calibration, graduation flags. |
| `fund_brain.py` | Ledger → next-cycle memory. |
| `evolution.py` | Typed postmortem, lab gate, lifecycle events. |
| `alerts.py` | Health conditions + optional webhook. |
| `backfill.py` | Derived daily NAV; does not write the ledger. |
| `fund_visualization.py` | README SVG from verified state. |
| `observability.py` | Structured JSON logs around CLI commands. |
| `growth.py` | Human dream telemetry. Not shown to the model. |

CLI entry points that matter operationally: `fund-context`, `fund-snapshot`,
`fund-run`, `monitor`, `fund-report`, `fund-postmortem`, `fund-evolve`,
`fund-alerts`, `fund-verify`.

Tests that lock the design: `tests/test_paper_fund.py` (vault + journal
gates + book walk), `tests/test_sizing.py`, `tests/test_monitor.py`,
`tests/test_attribution.py`, `tests/test_playbooks.py`,
`tests/test_evolution.py`, `tests/test_alerts.py`,
`tests/test_scheduled_script.py` (the two flags are on the apply line).

---

## 17. What this design refuses to become

- Not a live broker path, a second ledger, or an options book.
- Not a framework for the agent loop. Playbooks are files; the allocator is
  arithmetic; the monitor is a cron job.
- Not a system that trades because the cron fired. Forced activity at 15 bps
  round-trip with no measured edge is negative expectancy by construction.
- Not a system that treats next-cycle NAV as proof the last thesis was right.
- Not a system whose evolution loop can relax fees after a losing week.

Phase 6 in [PLAN.md](PLAN.md) is a **graduation checklist**, not more code:
200+ realistic closed trades, after-cost expectancy with CI above zero,
Sharpe > 1 on daily marks over six months, calibration error under 10 points,
costs under 20% of gross profit. The report already tracks the flags. They
will stay false for a long time, and that is correct.

---

## 18. How you know the design is actually running

Code on a laptop is not the fund. The design is live when:

1. `fund-verify` is green on the real ledger.
2. Scheduled apply uses `--code-owned-quotes --size-beliefs` (the shell
   script already does).
3. `monitor` has enforced at least one stop or target without a model.
4. `fund-report` shows expectancy, calibration, and sleeve cuts — and you
   treat the pre-sizing 13 cycles as a different sample.
5. A weekly `fund-evolve` has written a `postmortem_completed` event, even
   if every proposal is “nothing yet.”
6. Model cost in the report is a real number, not `$0` because nobody
   recorded tokens.

Until then the architecture is implemented in source and idle in production.
That is an operations problem, documented in [OPERATIONS.md](OPERATIONS.md),
not a missing module.
