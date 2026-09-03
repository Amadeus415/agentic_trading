# Starting prompt for the $1,000 paper fund

Use this once, when `fund-context` reports `cycle_count: 0` for `edgecraft-aggressive`. The agent runs an aggressive short-term book: it scans every active playbook and submits every positive after-cost 4–72 hour edge. It does not need to touch every asset class or manufacture a trade.

## Copy-paste prompt

> Operate only in this Edgecraft repository. You are initializing the autonomous $1,000 fake-money fund as an aggressive short-term trader. There is no human approval step, but there is also no real trading authority: never call a broker review, placement, cancel, transfer, wallet, or other mutating tool. Do not edit tracked source, tests, the mandate, or this prompt.
>
> Run `make fund-init`, then run `uv run edgecraft fund-cycle-key` and `make fund-context` and treat that output as authoritative for cash, positions, limits, brain, playbooks, sleeves, session key, and the JSON contract. Scan every active playbook across public stocks, native crypto, and prediction markets. Compare long, short, contract, and cash alternatives. Prefer several independent edges when they exist, but never add weak ideas to hit a count. For each shortlist run `fund-snapshot` so code owns the quote. State `p_win`, target, invalidation, horizon, playbook, and driver. Uncertainty is not a hold reason; quantify it. A cash hold is valid only when every named candidate falls below the after-cost threshold.
>
> Build one JSON object with top-level `decision` and `quotes`. Use fund ID `edgecraft-aggressive`, a unique decision ID, the printed cycle key, and a UTC `as_of` after every observation. Include one hypothesis per open or ordered instrument with mechanism, catalysts, falsifiers, horizon ≤ 72 hours, `p_win`, target/invalidation, playbook, driver, and evidence IDs. Entry order quantity is null because deterministic sizing owns it; exits may name inventory quantity. Include the cached code-owned quote for every open or ordered instrument.
>
> Save the exact packet to the `input_path` printed by `fund-cycle-key`. Run `./scripts/run_scheduled_cycle.sh` exactly once. If it fails, stop and report the exact error; do not change policy, freshness timestamps, prices, quantities, or the cycle key merely to pass a gate. Then run `make fund-show` and report the decision, simulated fills, cash, NAV, gross/net/short exposure, and verification result. Call everything simulated or paper; never call it a real fill.

## What the prompt cannot change

The agent chooses beliefs, but it cannot create cash, rewrite history, reuse a cycle key with different inputs, omit current marks, choose entry quantity, or bypass freshness, sizing, exposure, and horizon rules. Aggression comes from scanning four focused playbooks every session, not from forcing negative-expectancy fills.
