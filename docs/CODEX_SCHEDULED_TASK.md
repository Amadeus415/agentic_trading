# Daily Codex task

Codex is the research and decision layer. `paper_fund.py` is the accounting and risk authority. The scheduled task runs every day without routine human approval and can choose any supported stock, crypto, or prediction instrument, but every action remains simulated.

## Mandate: active, aggressive, short-term

The active fund (`edgecraft-aggressive`, mandate `examples/fund.mandate.aggressive.json`) is run as a high-tempo, risk-taking multi-position book. The agent is expected to search hard for trades every cycle, while never trading merely to look active:

- **Daily directional bets.** Take a view on today's or this week's tape — index direction, crypto momentum, event outcomes. Size conviction up to 60% of NAV in a single position.
- **Prediction markets are a core playbook.** Binary contracts on elections, data releases, sports, Fed decisions, geopolitics are the fund's native short-term, levered instrument. When a contract's price disagrees with your researched probability by enough to clear fees and slippage, take the side with positive expected value. Buy YES or NO; flip stale positions when probabilities move.
- **Shorts are first-class.** Deteriorating thesis, broken momentum, or an overpriced contract means short it — up to 100% of NAV in short exposure.
- **Cut losers fast.** A position that moved against its thesis is exited in the next cycle rather than defended. Re-entering is fine when evidence returns.
- **Leverage within the envelope.** Up to 3× NAV gross exposure and 4× NAV turnover per cycle. Rotate freely between ideas.
- **Portfolio breadth is earned.** Prefer roughly 3–12 independent positions when enough strong ideas exist. Fewer positions are correct when conviction is scarce; tiny decorative positions are not diversification.
- **Cash is the exception, not the default.** Hold cash only when broad research finds no defensible expected-value edge after costs.

The growth target never overrides deterministic policy or risk checks. Aggression lives inside the envelope; the code still rejects broken accounting, stale quotes, unsupported inventory, and over-limit sizing.

## Daily operating loop

1. Initialize or reopen the immutable $1,000 paper fund.
2. Read the current state, ledger-derived brain, and machine-readable input schema.
3. Mark every open position with a fresh public quote and test its falsifiers.
4. Scan a broad stock/crypto opportunity set, then research the best candidates deeply.
5. Compare candidates with every existing position and the cash alternative.
6. Produce one structured buy/sell/short/cover/hold decision journal with cited evidence and a current hypothesis for every open or ordered instrument.
7. Save the complete packet under `state/fund-inputs/`.
8. Run the fixed apply script once.
9. Verify and report the resulting book.

## Durable scheduled-task prompt

> Operate only in this Edgecraft repository. Manage the autonomous $1,000 fake-money fund end to end as an aggressive, short-term, risk-taking trader. Never call a broker review, placement, cancel, transfer, wallet, or other mutating tool. Never edit tracked source, tests, prompts, or `examples/fund.mandate.aggressive.json`. Generated cycle inputs may be written only under the gitignored `state/fund-inputs/` directory.
>
> Run `make fund-init`, then `make fund-context`. If `cycle_count` is zero, follow `docs/FUND_STARTING_PROMPT.md`; otherwise continue with this daily loop. Treat fund context as authoritative for cash, positions, limits, the ledger-derived brain, the $100,000 growth objective, and current capital stage. Search aggressively for opportunities across stocks, native crypto, and prediction markets, then express only researched edges with conviction up to the checked-in envelope (60% of NAV per position, 3× gross leverage, 1× NAV short exposure, 4× turnover). Aim for a real multi-position portfolio—roughly 3–12 independent positions when enough strong ideas exist—but never add weak or tiny decorative trades to hit a count. Prediction-market contracts are allowed when researched probability differs from price enough to clear fees and slippage. Exit any position whose thesis broke rather than defending it. Hold cash when no defensible edge survives costs; never manufacture conviction to satisfy the growth target.
>
> Mark every open position with a fresh quote even when exiting it. Re-evaluate every thesis against current public market data and primary sources: filings, issuer releases, economic data, direct exchange data, reputable news, and contract resolution rules. Start with a broad scan, shortlist the most asymmetric candidates, and compare long, short, contract, existing-position, and cash alternatives. Build one schema-valid JSON packet with top-level `decision` and `quotes`. Use fund ID `edgecraft-aggressive`, cycle key `YYYY-MM-DD` for today's UTC date, and a current UTC `as_of`. The decision must include `journal`: market regime, opportunity set, portfolio intent, what changed, lessons applied from `brain`, and one current structured hypothesis for every open or ordered instrument. Each hypothesis records stance, mechanism, catalysts, falsifiers, horizon, confidence, target/invalidation prices when meaningful, and embedded evidence IDs. Preserve direct source URLs, source/observation timestamps, concise claims, relevant instrument IDs, alternatives, and risks. Every order must cite embedded evidence. Quotes must cover every open position and every ordered instrument. A resolved prediction contract must use a sourced `settled` quote of exactly `0` or `1`; never guess a resolution.
>
> Save the exact packet to `state/fund-inputs/YYYY-MM-DD.json`, then run `./scripts/run_scheduled_cycle.sh` exactly once. On any failure, stop and report the exact error. Never alter prices, timestamps, evidence, quantities, policy, or cycle identity just to pass a gate, and never retry a changed request under the same cycle key. If a gate rejects sizing, resubmitting a smaller compliant version under a new manual cycle key is allowed; weakening evidence is not. Finally run `make fund-show` and `make fund-verify`, then report the thesis, simulated actions or hold, fees, cash, NAV, P&L, gross/net/short exposure, and hash-chain/accounting verification. Always describe fills as simulated.

## Fixed apply path

```bash
./scripts/run_scheduled_cycle.sh
```

The script uses only:

```text
examples/fund.mandate.aggressive.json
state/fund-inputs/YYYY-MM-DD.json
state/edgecraft-aggressive.db
```

`FUND_CONFIG` and `FUND_LEDGER` environment variables override those paths. The retired conservative book (`edgecraft-1k`) stays frozen and verifiable at `state/edgecraft-fund.db`.

It capitalizes only an empty fund, verifies the ledger, requires today's UTC input and a complete brain journal, applies one atomic fake-money cycle, and verifies the full history again. It contains no broker command.

## On-demand runs

When the owner asks Codex to “run the hedge fund,” follow the same loop. If a scheduled cycle already used today's `YYYY-MM-DD` key, use a clearly labeled unique manual key such as `manual-YYYY-MM-DDTHHMMSSZ` and a separate input filename. Run `uv run edgecraft fund-run` directly for that packet, then `fund-verify`. Never overwrite or reinterpret the scheduled cycle.

## Valid outcomes

- `hold`: evidence did not justify a change; marks and reasoning are still audited.
- `trade`: all proposed fake fills passed accounting and risk checks.
- rejection: the ledger was unchanged; report the actual validation reason.
- replay: the exact cycle was already applied; there are no duplicate fills.
