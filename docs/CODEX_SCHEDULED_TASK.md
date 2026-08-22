# Daily Codex task

Codex is the research and decision layer. `paper_fund.py` is the accounting and risk authority. The scheduled task runs every day without routine human approval and can choose any supported stock, crypto, or prediction instrument, but every action remains simulated.

## Daily operating loop

1. Initialize or reopen the immutable $1,000 paper fund.
2. Read the current state and machine-readable input schema.
3. Mark every open position with a fresh public quote.
4. Research material changes, alternatives, and new opportunities.
5. Produce one structured buy/sell/short/cover/hold decision with cited evidence.
6. Save the complete packet under `state/fund-inputs/`.
7. Run the fixed apply script once.
8. Verify and report the resulting book.

## Durable scheduled-task prompt

> Operate only in `/Users/colenba/02_pink_dolphin/01_Shipping/agentic_trading`. Manage Edgecraft's autonomous $1,000 fake-money fund end to end. Never call a broker review, placement, cancel, transfer, wallet, or other mutating tool. Never edit tracked source, tests, prompts, or `examples/fund.mandate.json`. Generated cycle inputs may be written only under the gitignored `state/fund-inputs/` directory.
>
> Run `make fund-init`, then `make fund-context`. If `cycle_count` is zero, follow `docs/FUND_STARTING_PROMPT.md`; otherwise continue with this daily loop. Treat fund context as authoritative, including its $100,000 growth objective and current capital stage. Research current public market data and relevant primary information across stocks, native crypto, and prediction markets. Seek asymmetric, evidence-backed opportunities capable of meaningful compounding, but never manufacture conviction to satisfy the target. Mark every existing position with a fresh quote even when holding. Re-evaluate the thesis, exit or hedge stale ideas, compare new opportunities, and consider cash. You may buy, sell, short, cover, or hold without human approval. Do not trade merely to be active and do not force exposure to every market. The growth target never overrides deterministic policy or risk checks.
>
> Build one schema-valid JSON packet with top-level `decision` and `quotes`. Use fund ID `edgecraft-1k`, cycle key `YYYY-MM-DD` for today's UTC date, and a current UTC `as_of`. Preserve direct source URLs, source/observation timestamps, concise claims, relevant instrument IDs, alternatives, and risks. Every order must cite embedded evidence. Quotes must cover every open position and every ordered instrument. A resolved prediction contract must use a sourced `settled` quote of exactly `0` or `1`; never guess a resolution.
>
> Save the exact packet to `state/fund-inputs/YYYY-MM-DD.json`, then run `./scripts/run_scheduled_cycle.sh` exactly once. On any failure, stop and report the exact error. Never alter prices, timestamps, evidence, quantities, policy, or cycle identity just to pass a gate, and never retry a changed request under the same cycle key. Finally run `make fund-status` and report the thesis, simulated actions or hold, fees, cash, NAV, P&L, gross/net/short exposure, and hash-chain/accounting verification. Always describe fills as simulated.

## Fixed apply path

```bash
./scripts/run_scheduled_cycle.sh
```

The script uses only:

```text
examples/fund.mandate.json
state/fund-inputs/YYYY-MM-DD.json
state/edgecraft-fund.db
```

It capitalizes only an empty fund, verifies the ledger, requires today's UTC input, applies one atomic fake-money cycle, and verifies the full history again. It does not invoke the older broker-aware autonomy service.

## On-demand runs

When the owner asks Codex to “run the hedge fund,” follow the same loop. If a scheduled cycle already used today's `YYYY-MM-DD` key, use a clearly labeled unique manual key such as `manual-YYYY-MM-DDTHHMMSSZ` and a separate input filename. Run `uv run edgecraft fund-run` directly for that packet, then verify. Never overwrite or reinterpret the scheduled cycle.

## Valid outcomes

- `hold`: evidence did not justify a change; marks and reasoning are still audited.
- `trade`: all proposed fake fills passed accounting and risk checks.
- rejection: the ledger was unchanged; report the actual validation reason.
- replay: the exact cycle was already applied; there are no duplicate fills.
