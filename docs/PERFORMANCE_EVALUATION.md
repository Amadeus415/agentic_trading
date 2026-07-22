# Performance evaluation

Edgecraft measures the agent against the S&P 500 from the first new decision
onward. It does not mix this experiment with deposits, old holdings, or returns
that happened before the evaluation started.

Every due cycle adds the same virtual contribution to three private shadow
books:

1. `agent` follows the model decision only when the deterministic risk engine
   approves it. A rejected decision or hold keeps cash.
2. `benchmark` buys the mandate benchmark, normally SPY.
3. `strategic` buys the mandate's fixed strategic weights without model
   judgment.

All three use the same point-in-time prices and the same configured cost
assumption. This makes cash drag and skipped decisions visible and keeps the
comparison independent of unrelated Robinhood deposits.

```bash
edgecraft performance \
  --ledger state/edgecraft.db \
  --mandate-id aggressive_market_day_live
```

The report includes value, contributions, costs, return on contributions,
time-weighted return, volatility, drawdown, excess return, tracking error, and
information ratio. It labels the result `measuring` for the first 20
observations. A few weeks are useful for operational evidence, but not enough
to establish repeatable alpha.

Broker execution is measured separately from strategy performance:

```bash
edgecraft execution-quality \
  --ledger state/edgecraft.db \
  --mandate-id aggressive_market_day_live
```

This compares each immutable decision price with the terminal average fill and
reports notional-weighted slippage, worst adverse slippage, fees, and any fill
that could not be measured. Rejected, partial, and unknown orders remain visible
in the operational ledger.

Before the model decides, Edgecraft also builds a content-hashed market snapshot
from completed adjusted daily bars. It covers the full universe plus the
benchmark and records momentum, volatility, downside risk, drawdown, RSI,
moving-average distance, beta, correlation, dollar liquidity, breadth, and
market regime. The cross-sectional score is a comparison aid, not a trading
signal or proof of expected return.

```bash
edgecraft intelligence \
  --mandate state/mandates/aggressive-market-day-live.json \
  --output state/intelligence/aggressive-market-day-live.json
```

The daily decision packet stores the exact snapshot, its completed-session date,
and its input checksum. Yahoo data can be revised later; the checksum makes that
revision risk visible instead of pretending the source is an institutional
point-in-time feed.

Before each new decision, Edgecraft also builds a compact decision-memory
packet. It includes recent thesis mechanisms, horizons, falsifiers, allocations,
and the next observable cash-flow-matched excess return, plus the aggregate
benchmark report. The packet is content-hashed and stored with the new decision.
It is feedback, not proof: short-term outcomes must not overrule a thesis's
declared horizon or induce optimization to a handful of observations.
