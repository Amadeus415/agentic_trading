# One fund, three loops

Edgecraft is an aggressive autonomous paper fund. Its pillars are understandability, simplicity, and YOLO: search often, take meaningful positions, accept substantial simulated losses, and change tactics when results deteriorate.

There is one researcher, one accounting engine, one bankroll, and one ledger. The dashboard reads that ledger; it cannot trade.

```text
Public sources → Codex beliefs → Python sizing → Simulated fills
                       ↑                              ↓
             Effective playbook versions ← Review ← Ledger
                                                      ↓
                                             Python exit monitor
```

## Trade

Codex scans every eligible strategy across stocks, crypto, and prediction markets. It records a source-backed probability, target, invalidation, driver, and a 4–72 hour horizon. Directional beliefs enter the sizing pass even when the researcher is uncertain. Missing orders or advisory `hold` wording cannot silently suppress a complete belief.

Python turns beliefs into orders. Matching existing inventory stays open; an opposing belief closes and reverses it. Exits execute before new entries, and shorts precede buys so their proceeds can fund independent longs. A reversal's entry still has to earn its place.

All behavioral settings live in `trading` in [the active configuration](../examples/fund.mandate.aggressive.json), validated by `policy.py`:

| Setting | Default |
| --- | --- |
| Kelly fraction | 1.00 |
| Shared driver ceiling | 60% of NAV |
| Prediction position ceiling | 60% of NAV |
| Incubating strategy ceiling | 60% of NAV |
| Active strategy ceiling | 120% of NAV across its positions |
| Review cadence | One day or 10 newly closed positions |
| Learning window | Most recent 20 closed positions per version |

Strategy budgets share the mandate's gross exposure budget, rather than being restricted to a combined 100% of NAV. Four starting strategies can receive 60% each within the existing 3× envelope. These are ceilings, not required investments. Driver, position, available cash, liquidity, and portfolio limits may reduce them.

Sizing uses a pure preview of the same accounting engine that applies the cycle. It finds a quantity that fits cash, displayed depth, costs, concentration, exposure, and turnover. It reserves modeled cost headroom so fees on later entries do not push an earlier position over its weight limit. It also rejects an entry when the modeled execution price erases its expected edge. Invalid quotes and unsupported inventory remain errors.

Previews do not write the ledger. The final packet is applied once, atomically. There is no changed-packet retry after a failed apply. Exact successful CLI replay uses the original recorded size and policy, even when current learning settings have changed.

Follow [the scheduled contract](CODEX_SCHEDULED_TASK.md) for the actual operating commands.

## Manage

The model-free monitor checks existing positions for stop, target, horizon expiry, and prediction settlement. The installer configures a five-minute interval. The installed LaunchAgent only changes when the installer is rerun.

A missing position mark prevents partial action. Stock exits wait for the equity session. Stops use the next observed price with modeled gap slippage; they are not guaranteed fills at the stop level. The current weekday/hours check does not model exchange holidays or early closes.

## Learn

Each trading session checks `review.due`. A review writes one typed postmortem and appends effective strategy versions to the ledger. New prompts, universes, and rule changes can start as funded forward paper experiments without mandatory backtests. Submitted backtest artifacts must still pass their stated validation checks.

The allocator examines each version's latest 20 completed positions. After 10 results, positive mean after-cost P&L promotes an incubating version; nonpositive mean freezes it. Positive active versions share budget according to mean P&L × √sample count, capped at 120% each. Frozen and retired versions receive no new capital. A review can propose a fresh replacement, whose record starts empty.

Partial exits accumulate into one result when the position becomes flat. Sizing calibration also uses completed positions, separated by version, instead of repeated hold observations. Rates shrink toward the current belief with a prior sample equal to the learning window; a handful of losses adjusts confidence gradually. Prediction probabilities are calibrated only against actual binary settlements; profitable early exits are not substituted for settlement outcomes.

This is a responsive paper-trading heuristic, not statistical proof of alpha. Different position sizes affect dollar expectancy. Read [the review contract](EVOLUTION.md) for patches, lifecycle, and replay rules.

## Keep the experiment honest

The initialized mandate, original deposit, costs, accounting, and simulated-only boundary are immutable. Behavioral settings cannot alter them. A different mandate requires a separately identified fund; it cannot inherit this fund's performance.

The ledger records losses as well as wins. Every cycle contains its decision, evidence, marks, fills, state, policy, allocation, and risk audit. `fund-verify` replays accounting and verifies the hash chain. The detailed money contract is [FUND_ACCOUNTING.md](FUND_ACCOUNTING.md).

| Code | Responsibility |
| --- | --- |
| `paper_fund.py` | Simulated execution, accounting, immutable mandate, ledger |
| `policy.py`, `sizing.py` | Behavioral settings and deterministic quantities |
| `marketdata/`, `monitor.py` | Public marks and mechanical exits |
| `attribution.py`, `allocator.py`, `evolution.py` | Outcomes, budget changes, effective versions |
| `cli.py`, `scripts/` | One operational path |
| `dashboard/` | Read-only presentation |

The optional lab provides research tools, not a second fund or a prerequisite for testing every new idea. Private state stays out of Git. Engineering tests and synthetic fixtures establish implementation behavior, never market profitability.
