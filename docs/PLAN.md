# Plan: from "agent that trades" to a fund that earns and evolves

Date: 2026-09-01. Written against ledger `state/edgecraft-aggressive.db` at cycle 13.

This document is the roadmap. Phases 0–5 are implemented; [DESIGN.md](DESIGN.md)
is the map of the resulting system. Phase 6 remains a graduation checklist, not
more code.

This is the plan for turning Edgecraft from a well-audited paper
simulator with a discretionary LLM trader into an autonomous fund that has a
measurable, positive, after-cost edge and that improves its own strategies
without a human rewriting prompts by hand.

The one-sentence thesis of the plan: **stop asking one model to be a good
trader; build a machine that discovers, tests, sizes, and retires trading
playbooks, and let the model do the research inside that machine.**

---

## 1. Where we are (honest diagnosis)

### 1.1 Track record so far

| Metric | Value |
|:--|--:|
| Cycles | 13 (4 all-cash holds, 7 trades, 2 holds with positions) |
| NAV | $932.13 (−6.8%) |
| Peak NAV | $1,189.88 (2026-08-31 US open) |
| Current drawdown | 21.7% |
| Realized P&L | −$74.19 |
| Fees paid | ≈ $3.15 |
| Round trips closed | 7 |

Closed trades, from the fills table:

| Instrument | Side | Held | Realized |
|:--|:--|:--|--:|
| polymarket:2252245:YES | long | 2 days | **+$99.44** |
| SOL-USD | short | 1.5 days | +$11.86 |
| BTC-USD | long | 1 day | +$7.37 |
| QQQ | short | 1 day | −$5.62 |
| QQQ | short | 3 days | −$1.52 |
| NVDA | long | 2 days | −$25.57 |
| polymarket:3953844:YES | long | 1.5 days | **−$160.16** |

Read this as a scientist, not as a scoreboard. Two binary contracts account for
almost all of the variance. The equity and crypto trades are small and net to
roughly zero after costs. With seven closed trades nothing here is
statistically distinguishable from noise, and the plan below has to be judged
by whether it produces the *sample size and measurement* needed to find out.

### 1.2 What is genuinely good and must be kept

- **Authority boundary.** Models propose; typed Decimal accounting authorizes.
  Append-only, hash-chained SQLite. This is the hardest part to get right and
  it is already right. Every phase below builds on it rather than around it.
- **Decision journal with falsifiable hypotheses.** Every position has a
  mechanism, target, invalidation, horizon, and confidence. That is exactly the
  data a learning loop needs. We are storing it and not yet using it.
- **Idempotent cycle keys, freshness gates, evidence provenance.** Solid.
- **Research lab** (`engine.py`, `walkforward.py`, CSCV/bootstrap validation).
  Currently disconnected from the fund. It becomes the validation gate in
  Phase 3.

### 1.3 Why the current design cannot become profitable as-is

1. **The mandate forces activity.** "Idle cash is rejected", "a week of holds is
   a process miss", "default to a trade". Forced trading at a fixed cadence with
   15 bps round-trip cost and no measured edge is negative expectancy by
   construction. Profitable funds trade when the edge appears, not when the
   cron fires.
2. **Sizing is discretionary.** The agent chose 1,000 YES shares at $0.16
   (16% of NAV) on a contract it itself scored at 34% confidence with a stated
   target of 0.35. Even taken at face value, Kelly sizing for that bet is a few
   percent of NAV. The code enforces exposure *caps* but not *expectancy-based
   sizing*. Caps stop blow-ups; they do not create profit.
3. **Stops and targets are only checked when the agent happens to run.** A
   falsifier of "XLE below $61.90" is meaningless if XLE trades at $60 for six
   hours between sessions and nobody marks it. The NAV path, peak NAV and
   drawdown are therefore artifacts of cycle timing. The $1,189 peak was an
   illiquid Polymarket mark at 0.28 that resolved to 0 a day later.
4. **The agent supplies its own quotes.** A ten-minute freshness window on
   stocks is enough to pick a favorable print. Nothing suggests this happened,
   but the design allows it, and any future automated learner will find it.
5. **No attribution.** The "brain" reports next-cycle NAV direction, which it
   correctly labels as not causal. We never compute the one thing that matters
   per hypothesis: *did price reach the target or the stop first, inside the
   horizon, and what was the realized return after cost?*
6. **No learning mechanism.** Adaptive prompts are hard-coded strings. Lessons
   are free text that the next model may or may not read. Nothing changes the
   behavior of the system based on outcomes.
7. **The target is a fantasy and it distorts behavior.** 58.5% a year, 100x in
   ten years, is beyond the best track records in history. A model told to hit
   it will rationally buy lottery tickets. Keep $100k as the long-run dream;
   remove it from the operating prompt.
8. **Simulation fidelity is optimistic.** Last price plus 10 bps for a
   1,000-share Polymarket order, no borrow cost on shorts, no overnight gap risk
   modeled, fractional index shorts, no market-hours check for stock fills.
   Paper profits that would not survive a real book are not profits.

---

## 2. Design principles for the next version

1. **Edge is a hypothesis about the market, not about a ticker.** The unit of
   evolution is a *playbook* (a repeatable setup with entry, exit, sizing and
   an expected reason it works), not a single trade.
2. **Code owns prices, marks, stops, and sizing. The model owns research.** The
   agent tells us *what* it believes and *how strongly*; deterministic code
   turns that into position size and enforces exits.
3. **Every belief is scored.** Confidence 0.60 must mean roughly 60% of such
   calls resolve favorably. Calibration is the agent's report card.
4. **Capital follows evidence.** Playbooks earn allocation by realized,
   after-cost, out-of-sample performance in their own sub-book. New ideas start
   tiny. Losers are retired automatically.
5. **The accounting engine and risk envelope stay immutable and human-owned.
   Everything above them is allowed to evolve.**
6. **Realistic before ambitious.** A simulator that lies is worse than none.

---

## 3. Target architecture

```text
┌──────────────────────────────────────────────────────────────────────┐
│  EVOLUTION LOOP (runs weekly, or every N closed trades)              │
│  postmortem → propose playbook / parameter / prompt diffs           │
│  → lab validation (walk-forward, CSCV, deflated Sharpe)              │
│  → promote to incubation sleeve → allocator scales or retires        │
└──────────────┬───────────────────────────────────────────────────────┘
               │ versioned playbook + prompt artifacts
┌──────────────▼───────────────────────────────────────────────────────┐
│  TRADING LOOP (each session)                                         │
│  market snapshot (code) → per-playbook research (agent)              │
│  → beliefs: p(win), target, stop, horizon                             │
│  → sizing engine (code, fractional Kelly, per-sleeve budget)          │
│  → paper_fund accounting + risk envelope (unchanged)                 │
└──────────────┬───────────────────────────────────────────────────────┘
               │ hourly
┌──────────────▼───────────────────────────────────────────────────────┐
│  MONITOR LOOP (code only, no model)                                  │
│  mark all positions from code-owned feeds                            │
│  enforce stop / target / horizon expiry as simulated fills           │
│  write attribution rows when a hypothesis resolves                   │
└──────────────────────────────────────────────────────────────────────┘
```

Three loops, three cadences. Only the trading loop calls a model on the hot
path. The monitor loop is what makes P&L real. The evolution loop is what makes
the fund self-improving.

---

## 4. Phases

Each phase leaves the repo runnable and ends with a measurable gate. Phase
numbers are dependency order, not calendar weeks.

### Phase 0: Tell the truth about performance (1 week)

Goal: turn the existing ledger into a dataset we can learn from.

Work:

- `src/edgecraft/attribution.py`: for every hypothesis ever journaled, compute
  outcome using the marks available in the ledger: `target_hit`,
  `stop_hit`, `expired`, `manually_closed`; realized return after cost; hold
  time; MFE/MAE (max favorable/adverse excursion) where marks exist.
- `fund-report` CLI: hit rate, expectancy per trade, profit factor, Sharpe from
  cycle-to-cycle NAV, exposure-weighted return, and the same cut by asset class,
  side, session slot, horizon bucket, and the model that produced the packet.
  Also a **calibration table**: stated confidence bucket vs realized win rate.
- Benchmarks in the same report: SPY buy-and-hold over the same window, and a
  "same instruments, same direction, fixed 5% sizing" counterfactual so we can
  separate selection skill from sizing luck.
- Store `runtime` (model, reasoning effort, prompt version) in the ledger. It is
  in the packets today but comes back `None` from `list_full_cycles`; fix that so
  we can compare models.
- Dashboard: one Attribution page. Nothing else.

Gate: the report runs on the current ledger and the README shows expectancy and
calibration next to the NAV chart.

### Phase 1: Make the simulator honest (1–2 weeks)

Goal: P&L that would survive contact with a real book.

Work:

- `src/edgecraft/marketdata/`: code-owned quote providers with a common
  interface. Start with what the agent already uses: Coinbase and Binance public
  REST for crypto, Nasdaq/Yahoo/Stooq for equities, Polymarket CLOB for
  contracts. Cache every fetch to disk under `state/marks/`.
- **Agent quotes become advisory.** The engine marks and fills from
  code-fetched prices at `decision.as_of`. If the agent's quote differs from the
  code quote by more than a tolerance, the cycle is rejected with a reason. This
  closes the cherry-pick hole and removes a whole class of prompt engineering.
- `edgecraft monitor` command, run hourly by cron: mark everything, then
  enforce each open hypothesis's `invalidation_price`, `target_price`, and
  `expected_horizon_hours` as simulated fills. Stops fill at the stop with an
  extra gap penalty when the bar gapped through it. This is the single biggest
  fidelity fix.
- Fill model upgrades in the mandate: market-hours check for stocks (queue to
  next open otherwise), borrow fee for stock shorts, Polymarket fills walk the
  order book depth instead of last price, minimum tick and share rounding.
- Use daily bars to backfill a correct mark-to-market NAV history for the 13
  existing cycles so the chart and drawdown are true.

Gate: `fund-verify` replays the history under the new fill rules; the monitor
has enforced at least one stop or target without a model in the loop.

### Phase 2: Code owns sizing, model owns beliefs (1 week)

Goal: stop the agent from choosing quantities.

Work:

- Extend the decision schema. Orders carry `direction`, `p_win`,
  `target_price`, `invalidation_price`, `horizon_hours`, `playbook_id`. The
  `quantity` field becomes optional and is ignored when the sizing engine is on.
- `src/edgecraft/sizing.py`: fractional Kelly (start at 0.25 Kelly) from
  `p_win` and the target/stop payoff ratio, times a **calibration haircut**
  derived from Phase 0 (if the agent's 0.60 calls win 45% of the time, shrink
  every 0.60 to 0.45). Cap by the existing envelope. Binary contracts are sized
  from stated probability vs market price with the same fractional Kelly. Under
  this rule the $160 lottery ticket becomes a $25 ticket.
- Minimum-edge gate: if expected value after fees, slippage and borrow is below
  a threshold, the order is dropped and logged as `below_edge_threshold`. This
  replaces "idle cash is rejected" with "trade when the math says so". Remove
  the idle-cash rejection and the "default to a trade" language from the
  prompts.
- Correlation guard: cap combined exposure across positions that share a
  driver (the current book has XLE long and QQQ short both riding one oil and
  rates story; the journal already says so). Simple version: the agent tags
  each hypothesis with a `driver` label and code caps exposure per driver.

Gate: sizing is deterministic from the belief packet and covered by unit tests
for long, short, binary, and correlated books.

### Phase 3: Playbooks and sleeves (2–3 weeks)

Goal: replace "one agent trades everything" with a portfolio of testable
strategies, each with its own record.

A **playbook** is a versioned JSON or Python spec:

```text
id, version, thesis (why should this earn money), universe, trigger,
entry rule, exit rule (target/stop/time), sizing hints, research prompt,
required evidence types, status: proposed | incubating | active | retired
```

Starting playbooks, chosen because a $1k book can plausibly have an edge in them
and because we have some evidence in the ledger already:

1. **Prediction-market resolution arbitrage.** Contracts near expiry whose
   resolution is determinable from a public data source (a Binance candle, a
   BLS print, a scheduled vote). The agent's job is to read the rule and the
   data, not to forecast. This is where the +$99 came from and where the −$160
   came from; the difference was that one was a data-lookup edge and the other
   was a price-path bet.
2. **Post-earnings drift.** Long or short for 1–3 days after a report with a
   large surprise and a same-direction price reaction. Well-documented anomaly;
   the NIO trade is a half-formed version of it.
3. **Crypto momentum with time stop.** 24–72h continuation after a large move
   confirmed by volume, with a hard time exit.
4. **Macro event reaction.** Scheduled data or policy events with a pre-written
   if/then map. Only trades if the outcome deviates from consensus.

Each playbook gets a **sleeve**: a virtual sub-book inside the one real ledger
(tag fills with `playbook_id`; NAV per sleeve is a derived view, not a second
accounting engine). The agent runs once per playbook per session with that
playbook's research prompt and universe, so the research is focused instead of
"scan everything".

`src/edgecraft/allocator.py`: capital per sleeve is a function of the sleeve's
realized after-cost record. Start every incubating sleeve at 5% of NAV. Scale
toward its Kelly-optimal share as trade count and confidence interval allow;
freeze a sleeve whose lower confidence bound goes negative after 30 trades;
retire it after 60. This is a multi-armed bandit over strategies, and it is the
core of self-evolution: the fund shifts money toward what works without a human
deciding.

Gate: at least three sleeves running with separate attribution; allocator
weights are derived from data and logged in each cycle's audit record.

### Phase 4: The evolution loop (2–3 weeks)

Goal: the system proposes and validates its own improvements.

Work:

- **Postmortem agent**, weekly or every 20 closed trades. Reads the attribution
  report and journals. Writes a structured `postmortem.json`: what worked, what
  failed, calibration gaps, suspected mechanism failures, and proposed changes.
  Changes are typed: `new_playbook`, `playbook_param`, `retire_playbook`,
  `research_prompt_edit`, `universe_edit`. It cannot propose envelope, fee,
  accounting, or paper-only changes.
- **Validation gate.** Proposals that can be backtested (playbook rules,
  parameters) run through the existing lab: walk-forward with CSCV and
  bootstrap, using the `marketdata` cache plus historical bars. Require positive
  out-of-sample expectancy and a deflated Sharpe above a threshold. Proposals
  that cannot be backtested (a new research prompt) go to a **shadow sleeve**:
  it produces packets that are recorded but not filled, and is promoted only
  after its paper record beats the incumbent.
- **Promotion path:** proposed → validated → incubating (5% of NAV) → active
  (allocator-sized) → retired. All transitions are ledger events. A human can
  veto by deleting a playbook file, but no human action is required for the
  loop to run.
- **Prompt versioning.** Research prompts live in `playbooks/<id>/prompt.md`
  with a version hash recorded in each cycle. A/B two prompt versions on the
  same playbook by splitting the sleeve; the allocator picks the winner.
- **Model choice is a parameter too.** Record model and reasoning effort per
  packet; let the postmortem recommend model changes per playbook based on
  calibration. Default new work to the current strongest available model.

Gate: one playbook has been proposed, validated, incubated and either promoted
or retired entirely by the loop, with the trail visible in the ledger.

### Phase 5: Autonomous local operations

- Run session cycles and the weekly postmortem as subscription-backed Codex
  Scheduled Tasks from a dedicated clean checkout. Fast-forward `main` before
  each run and keep private ledger state out of the public repository.
- Run the code-only monitor hourly with a macOS LaunchAgent. The host and Codex
  app must remain running; a small always-on box is the later portability path.
- Alerting: a Slack or email message when a cycle is rejected, the monitor
  fails to fetch marks, drawdown crosses 15% or 30%, or the chain fails to
  verify.
- Cost tracking: model spend per cycle recorded in the ledger. A fund that pays
  $3 in tokens to earn $2 is not profitable. Show this in the report.

### Phase 6: Graduation criteria and the real-money question (later)

The repo is deliberately paper-only and this plan keeps it that way. Whether to
ever connect real money is Amadeus's decision, not the agent's. The plan's job
is to produce evidence good enough to make that decision honestly.

Suggested graduation criteria before even discussing a live sleeve:

- 200+ closed trades in the active sleeves with realistic fills and enforced
  stops.
- After-cost expectancy positive with a 95% bootstrap confidence interval
  above zero.
- Sharpe above 1.0 on daily marked NAV over at least six months.
- Calibration error under 10 points in every confidence bucket.
- Model and data costs under 20% of gross profit.

If a live path is ever added it should be a separate mandate, a separate
ledger, a broker with a paper mode first (Alpaca, for instance), tiny fixed
capital, and the existing `deny_broker_tools.py` fence loosened only for that
one adapter with explicit human sign-off.

---

## 5. What to change in the prompts and mandate right now

These are small edits with an immediate effect and no new code:

1. Delete "idle cash is rejected", "default to a trade", and "a week of holds is
   a process miss" from `AGENTS.md`, `docs/CODEX_SCHEDULED_TASK.md`, and the
   adaptive prompts in `fund_brain.py`. Replace with: "Trade only when the
   stated edge clears cost after your calibration haircut. Cash is a position."
2. Remove the $100,000 target and "58.5% annualized" from everything the agent
   reads. Keep them in the README as the dream.
3. Require `p_win` per hypothesis and forbid bare "confidence". Words like
   confidence drift; probabilities can be scored.
4. Cap any single binary contract at 5% of NAV in the mandate until Phase 2
   sizing exists.
5. Require a `driver` tag per hypothesis so correlation is visible now, even
   before code enforces it.

---

## 6. Metrics that define success

| Metric | Now | Phase 2 target | Graduation |
|:--|--:|--:|--:|
| Closed trades | 8 | 50 | 200+ |
| After-cost expectancy per trade | unknown | measured | > 0, CI above 0 |
| Calibration error (max bucket) | unmeasured | measured | < 10 pts |
| Stops enforced by code | 0% | 100% | 100% |
| Quotes owned by code | 0% | 100% | 100% |
| Sleeves with independent record | 0 | 3 | 3+ |
| Playbooks promoted or retired by loop | 0 | 0 | ≥ 1 per month |
| Sharpe (daily marked NAV) | n/a | measured | > 1.0 |

---

## 7. What we are explicitly not doing

- Not building a second accounting engine, a live broker path, or an options
  book. The current boundaries are correct.
- Not adding a framework for the agent loop. Playbooks are files; the allocator
  is arithmetic; the monitor is a cron job. Keep it boring.
- Not chasing the 100x target with size. If the edge is real, compounding does
  the work. If it is not, no amount of leverage helps.

---

## 8. Suggested first two weeks

1. Phase 0 attribution and report, including the calibration table. This is
   the foundation for everything else and it needs no new data.
2. Prompt edits from section 5.
3. Phase 1 code-owned quotes and the hourly monitor with stop and target
   enforcement.
4. Backfill true daily NAV for the existing cycles and regenerate the chart.

At that point the fund will finally be able to answer the only question that
matters: after cost, with stops honored, does this agent have an edge? Every
later phase is about making that answer improve on its own.
