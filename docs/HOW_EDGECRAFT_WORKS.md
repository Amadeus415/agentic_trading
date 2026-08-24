# How Edgecraft works

In one sentence: Codex proposes a sourced portfolio decision, and `paper_fund.py` deterministically applies it to a persistent $1,000 fake-money ledger.

## Code path

1. `edgecraft fund-context` loads the immutable mandate, latest `FundState`, and compact ledger-derived brain.
2. Codex scans public markets, revisits prior outcomes, and writes a journaled `FundDecision` plus `FundQuote` objects.
3. `edgecraft fund-run` validates fund identity, scheduled freshness, and complete hypotheses for every open or ordered instrument.
4. `PaperFundLedger.execute_cycle()` starts an immediate SQLite transaction and enforces cycle idempotency.
5. `run_cycle_accounting()` settles resolved prediction contracts, applies explicit-side simulated fills, marks all positions, and checks risk.
6. The ledger stores the exact normalized inputs, fills, state, digest, and next hash-chained event in one commit.
7. `PaperFundLedger.verify()` starts from the original $1,000, replays every stored cycle, and compares the rebuilt book with each stored state.

## Why Codex does not own the balance

The input schema contains no cash field. The agent sees the current book but cannot replace it. Cash changes only through the one-time initialization or deterministic fill/settlement formulas. A cycle cannot create a contribution.

## Why arbitrary markets do not imply arbitrary authority

There is no instrument whitelist. An instrument ID only has to be syntactically valid and classified as stock, crypto, or prediction. That freedom is safe because it enters a fake ledger and still requires a fresh sourced quote, relevant evidence, valid side/inventory, and risk room.

## Where to read next

- [Accounting formulas and invariants](FUND_ACCOUNTING.md)
- [Starting prompt](FUND_STARTING_PROMPT.md)
- [Daily scheduled task](CODEX_SCHEDULED_TASK.md)
- `src/edgecraft/paper_fund.py`
- `src/edgecraft/fund_brain.py`
- `tests/test_paper_fund.py`

The older research/backtest modules remain separate so causal experiment code does not become portfolio authority.
