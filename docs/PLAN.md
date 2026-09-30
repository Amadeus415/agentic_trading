# What counts as success

Edgecraft should be easy to explain: Codex researches, Python sizes and manages simulated positions, and a daily review tests new strategy versions using the same append-only ledger.

## Implemented in this refactor

- Full configured Kelly fraction, larger prediction and strategy budgets, and allocations that can use the existing gross exposure envelope.
- Deterministic cash/liquidity/risk fitting so an oversized candidate need not reject every other idea.
- Exits and reversals within the same cycle, with budget released by actual planned exits.
- Funded forward paper experiments for prompts and rules; backtests are optional evidence.
- Daily-or-10-trade reviews, recent per-version outcomes, promotion and freezing after 10 results.
- Completed-position learning so partial exits and repeated hold observations cannot multiply sizing evidence.
- A UTC close slot that allows an equity scan before market close in both Pacific clock regimes.
- Five-minute monitor installation and compact documentation of one operating path.

The production ledger and installed schedules are separate from source changes. [Operations](OPERATIONS.md) describes deployment and installation. Always verify the deployed revision and next accepted cycle before describing a change as operational.

## What still needs forward evidence

Aggressiveness is a behavior, not a profitable edge. Establish it with sourced candidates and meaningful simulated fills. Establish improvement with a new version that earns budget on its own completed positions and a losing version that loses budget. Establish profitability with sustained after-cost NAV growth and a date-aligned S&P comparison.

Current simulation limits remain: sampled public quotes, uncertain executable liquidity and borrow availability, weekday-only equity hours without holidays, and a dividend-excluding benchmark. Full Kelly depends heavily on estimated probabilities. Recent dollar P&L is a fast allocation heuristic, affected by position size and small samples.

Keep collecting honest forward outcomes. Add a component only when a measured problem calls for it. Real-money execution is outside this project.
