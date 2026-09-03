# Scheduled Codex task

Codex is the research and decision layer. `paper_fund.py` is the accounting and risk authority. The scheduled task runs several times per weekday without routine human approval and can choose any supported stock, crypto, or prediction instrument, but every action remains simulated.

## Mandate: active, aggressive, short-term

The active fund (`edgecraft-aggressive`, mandate `examples/fund.mandate.aggressive.json`) is a high-tempo short-term trader. The job is to take researched 4–72 hour views, not to sit in cash until a formal model appears.

- **Multiple sessions and four scans.** Fire US-open, US-close, and off-hours slots. Evaluate every active playbook each time. Trade eagerness comes from a broad repeated search, not a forced fill.
- **Quantify every candidate.** A sourced catalyst, `p_win`, target, invalidation, driver, playbook, and 4–72h horizon define the belief. Uncertainty is not a hold reason; deterministic sizing decides whether the edge clears costs.
- **Cash must win the comparison.** Cash is a position. It is valid only when the journal names the researched candidates and the sizing audit drops each one below the after-cost threshold.
- **Code owns size.** The agent returns beliefs with null entry quantity. Fractional Kelly, calibration, sleeves, driver caps, and the existing risk envelope determine notional.
- **Prediction markets are a core playbook.** Binary contracts on data releases, sports, Fed decisions, and geopolitics are native short-term instruments. When your researched probability differs from the quote by enough to clear fees and slippage, take the side. Buy YES or NO; flip stale positions when probabilities move.
- **Shorts are first-class.** Deteriorating thesis, broken momentum, or an overpriced contract means short it — up to 100% of NAV in short exposure.
- **Cut losers inside the horizon.** A position that hit its falsifier is exited this session rather than defended. Re-entering is fine when evidence returns.
- **Leverage within the envelope.** Up to 3× NAV gross exposure and 4× NAV turnover per cycle. Rotate freely between ideas.
- **Portfolio breadth is earned.** Prefer roughly 3–8 independent short-term positions when enough strong ideas exist. Tiny decorative tickets are not diversification.
- **Hold is measured, not fearful.** Existing positions must still pass falsifiers. A cash hold must show the rejected opportunity set and expected-value math. Flattening is `sell` or `cover`.

The long-run dream never enters the operating decision. Aggression lives in research breadth and fast invalidation; code rejects broken accounting, stale or non-code-owned quotes, unsupported inventory, over-limit sizing, and theses beyond 72 hours.

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
3. Run `fund-snapshot` for open positions and every shortlisted candidate; these cached public marks own fills.
4. Scan every active playbook, then research the best short-term candidates deeply.
5. Compare candidates with existing positions and cash using `p_win`, payoff, costs, and shared drivers.
6. Produce one structured journal. Entry quantity is null; code sizes beliefs. Horizons must be ≤ 72 hours.
7. Save the complete packet under `state/fund-inputs/`.
8. Run the fixed apply script once.
9. Verify the resulting book, regenerate the public SVG, and publish only that snapshot.

## Durable scheduled-task prompt

> Operate only in this clean Edgecraft runtime checkout. Manage the autonomous $1,000 fake-money fund end to end as an aggressive short-term trader. Never call a broker review, placement, cancel, transfer, wallet, or other mutating tool. Never edit tracked source, tests, prompts, or `examples/fund.mandate.aggressive.json`. Generated cycle inputs may be written only under the gitignored `state/fund-inputs/` directory.
>
> Run `./scripts/prepare_local_runtime.sh` first, then `uv run edgecraft fund-cycle-key` and `make fund-context`. Treat context as authoritative for cash, positions, limits, brain, playbooks, sleeves, and cycle identity. Scan every active playbook aggressively across stocks, native crypto, and prediction markets. For each shortlist run `fund-snapshot`. State `p_win`, target, invalidation, horizon, playbook, and driver; set entry quantity to null. Uncertainty is not a hold reason. Submit every belief that clears estimated costs, but do not manufacture a fill: cash is valid only when every named candidate loses the after-cost comparison. Exit broken theses immediately.
>
> Re-evaluate every thesis against primary public sources. Build one schema-valid packet using the printed cycle key and an `as_of` after all observations. The journal covers the full scanned opportunity set and one current hypothesis for every open or ordered instrument. Each hypothesis records stance, mechanism, catalysts, falsifiers, horizon ≤ 72 hours, `p_win`, target/invalidation, playbook, driver, and evidence IDs. Quotes must be the cached code-owned marks. A resolved prediction contract uses its exact authoritative settlement rule and a sourced terminal mark of `0` or `1`; never substitute a context source.
>
> Save the exact packet to the `input_path` printed by `fund-cycle-key`, then run `./scripts/run_scheduled_cycle.sh` exactly once. On any failure, stop and report the exact error. Never alter prices, timestamps, evidence, quantities, policy, or cycle identity just to pass a gate, and never retry a changed request under the same cycle key. If a gate rejects sizing, resubmitting a smaller compliant version under a new manual cycle key is allowed; weakening evidence is not. After a successful apply and verification, run `./scripts/publish_fund_visualization.sh`; it stages and pushes only `assets/fund-progress.svg`, never ledger state or unrelated work. Finally run `make fund-show` and `make fund-verify`, then report the thesis, simulated actions, fees, cash, NAV, P&L, gross/net/short exposure, visualization publication, and hash-chain/accounting verification. Always describe fills as simulated.

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

It capitalizes only an empty fund, verifies the ledger, requires this UTC session's input and a complete brain journal, applies one atomic fake-money cycle, verifies the full history again, and regenerates `assets/fund-progress.svg` plus the dashboard's gitignored `state/fund-report.json`. The separate publish script commits only that public SVG. Neither script contains a broker command.

## On-demand runs

When the owner asks Codex to “run the hedge fund,” follow the same loop. If this session's key is already used, use a clearly labeled unique manual key such as `manual-YYYY-MM-DDTHHMMSSZ` and a separate input filename. Run `uv run edgecraft fund-run` directly for that packet, then `fund-verify`. Never overwrite or reinterpret the scheduled cycle.

## Valid outcomes

- `trade`: all proposed fake fills passed accounting and risk checks. This is the expected scheduled outcome when the book is cash or a thesis changed.
- `hold`: positions remain intact or every researched entry was dropped by the after-cost sizing gate.
- rejection: the ledger was unchanged; report the actual validation reason.
- replay: the exact cycle was already applied; there are no duplicate fills.
