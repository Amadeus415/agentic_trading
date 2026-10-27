# The pilot

Before Nightshift was a benchmark, it was a single paper fund run by scheduled Claude Code sessions, from August to October 2026. Its code is tagged `pilot` (the multi-asset first version is also tagged `v1-multi-asset`), and the full record is in the git history before the benchmark overhaul.

| Era | Dates | Design | Result (simulated) |
| --- | --- | --- | --- |
| v1: multi-asset | Aug 22 – Oct 5 | Claude proposed stock, crypto and prediction trades; Python sized them | $1,000 → $1,020 (+2%), 27% max drawdown, 22 closed trades |
| v2: prediction markets | Oct 17 – Oct 26 | Python sized Claude's beliefs with full Kelly and a forecast-trust estimate | $1,000 → $425.50 (−57%), 64% drawdown, 19 closed trades |
| v3: facts | Oct 26 | Trade only "already decided by a primary source" calls | Superseded by the benchmark before it ran |

The code-only control fund lost 8% over v2's window.

## What carried over

- **The harness designer's strategy got tested, not the agent's.** Python owned sizing, trust and risk, so v2's loss mostly measured those rules. In the benchmark the agent owns strategy, and the harness enforces only cash, real fills and fees.
- **Forecasts measure judgment faster than P&L.** Across 368 settled v2 forecasts, Claude did worse than the market price exactly where it disagreed with it. Forecast skill against the market became a primary metric.
- **Fills must favor the market.** Real order books, venue fees and bid valuation came from the pilot and stayed.
- **One unproven-but-promising signal.** When the agent said a published source had already decided a contract the market still doubted, it was right 18 of 18 times. The benchmark doesn't build this in; an agent that finds it on its own should show up in its forecast skill.
