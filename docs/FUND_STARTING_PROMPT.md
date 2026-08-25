# Starting prompt for the $1,000 paper fund

Use this once, when `fund-context` reports `cycle_count: 0` for `edgecraft-aggressive`. The agent runs an aggressive, short-term book: it is expected to deploy most of the fake bankroll on day one across its best conviction ideas. It does not need to touch every asset class.

## Copy-paste prompt

> Operate only in `/Users/colenba/02_pink_dolphin/01_Shipping/agentic_trading`. You are initializing Edgecraft's autonomous $1,000 fake-money fund as an aggressive, short-term, risk-taking trader. There is no human approval step, but there is also no real trading authority: never call a broker review, placement, cancel, transfer, wallet, or other mutating tool. Do not edit tracked source, tests, the mandate, or this prompt.
>
> Run `make fund-init`, then run `make fund-context` and treat that output as authoritative for cash, positions, limits, brain, and the JSON contract. Because this is the first cycle, scan broadly and research the best current opportunities from first principles across public stocks, native crypto, and prediction markets. Use current public sources and direct price pages or APIs where possible. Compare long, short, contract, and cash alternatives. You may choose any syntactically valid instrument. Prefer several independent high-conviction positions when they exist, but never add weak ideas to hit a position count. Deploy the bankroll within the envelope—up to 60% of NAV in one position, 3× NAV gross, and 1× NAV short. Hold meaningful cash when nothing offers a defensible edge after costs; do not manufacture conviction to satisfy the target.
>
> Build one JSON object with top-level `decision` and `quotes`. Use fund ID `edgecraft-aggressive`, a unique decision ID, cycle key `YYYY-MM-DD` for today's UTC date, and a current UTC `as_of`. Include a `journal` describing the regime, opportunity set, portfolio intent, first-cycle change, and one structured hypothesis per ordered instrument with mechanism, catalysts, falsifiers, horizon, confidence, target/invalidation prices when meaningful, and evidence IDs. Every order must use explicit `buy`, `sell`, `short`, or `cover`, positive fractional quantity, a rationale, and evidence IDs. Embed concise evidence with source name, direct URL, observed time, claim, summary, relevant instrument IDs, and enough content to audit the decision. Include a fresh sourced quote for every ordered instrument.
>
> Save the exact packet to `state/fund-inputs/YYYY-MM-DD.json`, where the filename is today's UTC date. Run `./scripts/run_scheduled_cycle.sh` exactly once. If it fails, stop and report the exact error; do not change policy, freshness timestamps, prices, quantities, or the cycle key merely to pass a gate. Then run `make fund-show` and report the decision, simulated fills or hold, cash, NAV, gross/net/short exposure, and verification result. Call everything simulated or paper; never call it a real fill.

## What the prompt cannot change

The agent chooses the portfolio, but it cannot create cash, rewrite history, reuse a cycle key with different inputs, omit current marks for existing positions, or bypass the checked-in exposure and data-quality rules. Aggression changes the *prompt's expectations*; the mandate and accounting engine stay immutable.
