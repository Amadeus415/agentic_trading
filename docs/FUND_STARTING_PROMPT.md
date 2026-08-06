# Starting prompt for the $1,000 paper fund

Use this once, when `fund-context` reports `cycle_count: 0`. The agent is free to invest all, some, or none of the fake bankroll. It does not need to touch every asset class.

## Copy-paste prompt

> Operate only in `/Users/colenba/02_pink_dolphin/01_Shipping/agentic_trading`. You are initializing Edgecraft's autonomous $1,000 fake-money fund. There is no human approval step, but there is also no real trading authority: never call a broker review, placement, cancel, transfer, wallet, or other mutating tool. Do not edit tracked source, tests, the mandate, or this prompt.
>
> Run `make fund-init`, then run `make fund-context` and treat that output as authoritative for cash, positions, limits, and the JSON contract. Because this is the first cycle, research the current opportunity set from first principles across public stocks, native crypto, and prediction markets. Use current public sources and direct price pages or APIs where possible. Compare long, short, and cash alternatives. You may choose any syntactically valid instrument and may deploy all, some, or none of the bankroll. Do not force a trade or force representation from each market.
>
> Build one JSON object with top-level `decision` and `quotes`. Use fund ID `edgecraft-1k`, a unique decision ID, cycle key `YYYY-MM-DD` for today's UTC date, and a current UTC `as_of`. Every order must use explicit `buy`, `sell`, `short`, or `cover`, positive fractional quantity, a rationale, and evidence IDs. Embed concise evidence with source name, direct URL, observed time, claim, summary, relevant instrument IDs, and enough content to audit the decision. Include a fresh sourced quote for every ordered instrument. Use `action=hold` and no orders if the evidence does not justify exposure.
>
> Save the exact packet to `state/fund-inputs/YYYY-MM-DD.json`, where the filename is today's UTC date. Run `./scripts/run_scheduled_cycle.sh` exactly once. If it fails, stop and report the exact error; do not change policy, freshness timestamps, prices, quantities, or the cycle key merely to pass a gate. Then run `make fund-status` and report the decision, simulated fills or hold, cash, NAV, gross/net/short exposure, and verification result. Call everything simulated or paper; never call it a real fill.

## What the prompt cannot change

The agent chooses the portfolio, but it cannot create cash, rewrite history, reuse a cycle key with different inputs, omit current marks for existing positions, or bypass the checked-in exposure and data-quality rules.
