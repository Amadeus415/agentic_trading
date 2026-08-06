# Performance evaluation

The experiment measures one persistent bankroll. It does not use deposits, contribution-adjusted returns, or resets.

```text
P&L          = current NAV - $1,000
total return = current NAV / $1,000 - 1
drawdown     = (peak NAV - current NAV) / peak NAV
```

Run:

```bash
make fund-performance
```

The report includes current NAV, P&L, total return, maximum recorded drawdown, positive/negative cycle counts, holds, trades, simulated fill count, and the immutable per-cycle cash/NAV/exposure history.

The report stays in `measuring` status for the first 20 cycles. Even after that, raw return does not establish skill. A useful evaluation eventually needs a long frozen period, a suitable benchmark, comparable timestamps, costs, and enough independent decisions to separate luck from repeatable edge.

The preserved research lab still reports backtest and walk-forward metrics for strategy experiments. Those results do not add cash to the live paper book and are not its performance history.
