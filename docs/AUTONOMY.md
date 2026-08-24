# Autonomy

Edgecraft autonomy means Codex can research, decide, and update the fake-money portfolio without routine human approval. It does not mean the model controls accounting or real assets.

## Authority split

| Codex decides | Deterministic code decides |
|:--|:--|
| What public markets to research | Whether the input schema is valid |
| Whether to buy, sell, short, cover, or hold | Whether quotes are fresh and complete |
| Instruments and fractional quantities | Whether inventory and cash accounting are valid |
| Thesis, alternatives, risks, and evidence | Whether exposure, turnover, concentration, and drawdown limits pass |
| Structured hypotheses and lessons applied | Whether every live/ordered instrument has a current journal entry |

The active domain has no live mode. `FundMandate` contains only fake-money accounting and risk parameters. `PaperFundLedger` contains no broker import or execution adapter.

## Daily loop

```text
fund-init → fund-context + fund brain → broad public research → JSON decision journal
→ preflight verification → atomic simulated cycle → full replay verification
```

The checked-in automation prompt is in [CODEX_SCHEDULED_TASK.md](CODEX_SCHEDULED_TASK.md). The first-run prompt is in [FUND_STARTING_PROMPT.md](FUND_STARTING_PROMPT.md).

## Failure behavior

- Missing, future, stale, duplicate, or asset-mismatched quotes reject the cycle.
- Invalid evidence references or unsupported sides reject before accounting.
- Oversells, over-covers, illegal side crossing, insufficient cash, or risk-limit violations reject atomically.
- A missing current input stops the scheduled script before ledger mutation.
- The same request under the same cycle key is an idempotent replay; a changed request is rejected.
- A ledger or accounting replay failure stops the schedule.
- A missing journal or missing hypothesis for an open/ordered instrument stops the schedule.

A hold is a complete autonomous decision, not a failure.

## Learning loop

`fund-context` and `fund-brain` expose a compact deterministic memory built from
the immutable paper ledger. It includes recent theses, next-cycle NAV direction,
fees, realized winning and losing exits, current unrealized P&L, rejections, and
the latest structured hypothesis for each instrument. The agent must use this
feedback to revise its portfolio, but the report explicitly avoids causal
attribution: a later NAV change can combine market moves, costs, and new trades.
