# Scheduled Codex task

Codex is the research and decision layer. `paper_fund.py` is the accounting and risk authority. The scheduled task runs several times per weekday without routine human approval and can choose any supported stock, crypto, or prediction instrument, but every action remains simulated.

## Mandate: active, aggressive, short-term

The active fund (`edgecraft-aggressive`, mandate `examples/fund.mandate.aggressive.json`) is a high-tempo short-term trader. The job is to take researched 4–72 hour views, not to sit in cash until a formal model appears.

- **Multiple sessions per week, not one daily meditation.** Fire at least the US-open and US-close slots on weekdays, plus at least one off-hours or weekend slot so crypto and prediction markets can move. Target several simulated fills per week. A week of all-cash holds is a process miss.
- **Default to a trade.** A sourced catalyst, target, invalidation, size, and 4–72h horizon **is** the edge definition. Lack of a calibrated probability model is not a hold reason. “Price moved” is not enough by itself, but a public catalyst plus a defined payoff/invalidation is enough.
- **Idle cash is rejected.** If the book is 100% cash, the scheduled packet must be `action=trade` with researched orders. Accounting will reject an all-cash hold. U.S. cash-equity close is not a reason to stay flat; native crypto and prediction markets trade anyway.
- **Daily directional bets.** Take a view on this session or this week’s tape — index direction, single-name catalysts, crypto momentum, event contracts. Size conviction up to 60% of NAV in a single position.
- **Prediction markets are a core playbook.** Binary contracts on data releases, sports, Fed decisions, and geopolitics are native short-term instruments. When your researched probability differs from the quote by enough to clear fees and slippage, take the side. Buy YES or NO; flip stale positions when probabilities move.
- **Shorts are first-class.** Deteriorating thesis, broken momentum, or an overpriced contract means short it — up to 100% of NAV in short exposure.
- **Cut losers inside the horizon.** A position that hit its falsifier is exited this session rather than defended. Re-entering is fine when evidence returns.
- **Leverage within the envelope.** Up to 3× NAV gross exposure and 4× NAV turnover per cycle. Rotate freely between ideas.
- **Portfolio breadth is earned.** Prefer roughly 3–8 independent short-term positions when enough strong ideas exist. Tiny decorative tickets are not diversification.
- **Hold is for live theses, not for fear.** `hold` is valid only when existing positions still pass their falsifiers and no rotation is warranted. Flattening is `sell` or `cover`. Going to cash and staying there is not a resting state.

The growth target never overrides deterministic policy or risk checks. Aggression lives inside the envelope; the code still rejects broken accounting, stale quotes, unsupported inventory, over-limit sizing, all-cash scheduled holds, and theses longer than 72 hours.

## Session keys

Use the current UTC session, not a calendar date:

| UTC hours | Slot | Cycle key |
|---|---|---|
| 13:00–15:59 | `session-eu` | `YYYY-MM-DD-session-eu` |
| 16:00–19:59 | `session-us-open` | `YYYY-MM-DD-session-us-open` |
| 20:00–22:59 | `session-us-close` | `YYYY-MM-DD-session-us-close` |
| 23:00–12:59 | `session-offhours` | `YYYY-MM-DD-session-offhours` |

```bash
uv run edgecraft fund-cycle-key
```

Save the packet to the printed `input_path`. The apply script requires that exact `cycle_key`.

## Operating loop

1. Initialize or reopen the immutable $1,000 paper fund.
2. Read the current state, ledger-derived brain, session key, and machine-readable input schema.
3. Mark every open position with a fresh public quote and test its falsifiers.
4. Scan a broad stock/crypto/prediction opportunity set, then research the best short-term candidates deeply.
5. Compare candidates with every existing position and the cash alternative. Cash wins only when a live book is already deployed and nothing new beats it after costs.
6. Produce one structured buy/sell/short/cover decision journal with cited evidence and a current hypothesis for every open or ordered instrument. Horizons must be ≤ 72 hours.
7. Save the complete packet under `state/fund-inputs/`.
8. Run the fixed apply script once.
9. Verify and report the resulting book.

## Durable scheduled-task prompt

> Operate only in this Edgecraft repository. Manage the autonomous $1,000 fake-money fund end to end as an aggressive short-term trader. Never call a broker review, placement, cancel, transfer, wallet, or other mutating tool. Never edit tracked source, tests, prompts, or `examples/fund.mandate.aggressive.json`. Generated cycle inputs may be written only under the gitignored `state/fund-inputs/` directory.
>
> Run `make fund-init`, then `uv run edgecraft fund-cycle-key` and `make fund-context`. If `cycle_count` is zero, follow `docs/FUND_STARTING_PROMPT.md`; otherwise continue with this session loop. Treat fund context as authoritative for cash, positions, limits, the ledger-derived brain, the current session key, the $100,000 growth objective, and current capital stage. This is an active 4–72 hour book. Search aggressively across stocks, native crypto, and prediction markets, then submit researched orders inside the envelope (60% of NAV per position, 3× gross leverage, 1× NAV short exposure, 4× turnover). Prefer 3–8 independent short-term positions when strong ideas exist; do not add tiny decorative tickets. If the book is 100% cash, you must trade — a scheduled hold will be rejected. U.S. cash-equity close is not a reason to stay flat. A sourced catalyst, target, invalidation, and size is a valid thesis; do not hold because you lack a calibrated probability model. Prediction-market contracts are in play when researched probability differs from price enough to clear fees and slippage. Exit any position whose thesis broke rather than defending it. Hold only while existing theses remain intact.
>
> Mark every open position with a fresh quote even when exiting it. Re-evaluate every thesis against current public market data and primary sources: filings, issuer releases, economic data, direct exchange data, reputable news, and contract resolution rules. Start with a broad scan, shortlist the most asymmetric 4–72h candidates, and compare long, short, contract, existing-position, and cash alternatives. Build one schema-valid JSON packet with top-level `decision` and `quotes`. Use fund ID `edgecraft-aggressive`, the cycle key printed by `fund-cycle-key`, and a current UTC `as_of`. The decision must include `journal`: market regime, opportunity set, portfolio intent, what changed, lessons applied from `brain`, and one current structured hypothesis for every open or ordered instrument. Each hypothesis records stance, mechanism, catalysts, falsifiers, horizon ≤ 72 hours, confidence, target/invalidation prices, and embedded evidence IDs. Preserve direct source URLs, source/observation timestamps, concise claims, relevant instrument IDs, alternatives, and risks. Every order must cite embedded evidence. Quotes must cover every open position and every ordered instrument. A resolved prediction contract must use a sourced `settled` quote of exactly `0` or `1`; never guess a resolution.
>
> Save the exact packet to the `input_path` printed by `fund-cycle-key`, then run `./scripts/run_scheduled_cycle.sh` exactly once. On any failure, stop and report the exact error. Never alter prices, timestamps, evidence, quantities, policy, or cycle identity just to pass a gate, and never retry a changed request under the same cycle key. If a gate rejects sizing, resubmitting a smaller compliant version under a new manual cycle key is allowed; weakening evidence is not. Finally run `make fund-show` and `make fund-verify`, then report the thesis, simulated actions, fees, cash, NAV, P&L, gross/net/short exposure, and hash-chain/accounting verification. Always describe fills as simulated.

## Fixed apply path

```bash
./scripts/run_scheduled_cycle.sh
```

The script uses only:

```text
examples/fund.mandate.aggressive.json
state/fund-inputs/YYYY-MM-DD-session-*.json
state/edgecraft-aggressive.db
```

`FUND_CONFIG` and `FUND_LEDGER` environment variables override those paths. The retired conservative book (`edgecraft-1k`) stays frozen and verifiable at `state/edgecraft-fund.db`.

It capitalizes only an empty fund, verifies the ledger, requires this UTC session's input and a complete brain journal, applies one atomic fake-money cycle, and verifies the full history again. It contains no broker command.

## On-demand runs

When the owner asks Codex to “run the hedge fund,” follow the same loop. If this session's key is already used, use a clearly labeled unique manual key such as `manual-YYYY-MM-DDTHHMMSSZ` and a separate input filename. Run `uv run edgecraft fund-run` directly for that packet, then `fund-verify`. Never overwrite or reinterpret the scheduled cycle.

## Valid outcomes

- `trade`: all proposed fake fills passed accounting and risk checks. This is the expected scheduled outcome when the book is cash or a thesis changed.
- `hold`: existing positions were marked and their theses still hold; no new orders. Illegal when the book is 100% cash.
- rejection: the ledger was unchanged; report the actual validation reason.
- replay: the exact cycle was already applied; there are no duplicate fills.
