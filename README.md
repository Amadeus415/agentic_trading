# Edgecraft

Edgecraft is a local, point-in-time stock-strategy research terminal. It combines an event-driven Python backtester with a React experiment UI, realistic next-session execution, recurring cash contributions, modern strategy templates, and adversarial validation intended to make weak ideas fail early.

It is research software, not investment advice and not a live-trading system. Backtests can be wrong even when the code is correct.

## What is included

- Adjusted daily OHLCV download and versioned local CSV caching
- Deterministic synthetic regime data for offline demos and repeatable tests
- Close-signal → next-session-open execution to prevent same-bar look-ahead
- Fractional quantities, cash constraints, spread, slippage, commissions, rejected/partial sizing, contributions, and an auditable fill ledger
- Multi-symbol portfolios and six included strategy families
- Block-bootstrap confidence intervals, Deflated Sharpe Ratio (DSR), and Combinatorially Symmetric Cross-Validation Probability of Backtest Overfitting (CSCV/PBO)
- A FastAPI research API and responsive dependency-free web terminal
- A multi-view run explorer for portfolio value, gains versus deposits, drawdown, idle cash, exposure, strategy isolation, and fill-level inspection
- Temporal-isolation, data-validation, engine, research, and API tests

## Included strategies

| Strategy | Purpose |
| --- | --- |
| Plain DCA | Unconditional baseline. Every conditional DCA should beat this after costs and cash drag. |
| Value-tilted DCA | Drawdown/RSI entry with a forced-buy deadline that prevents indefinite market timing. |
| Trend + volatility target | Time-series moving-average regime filter with realized-volatility exposure scaling. |
| Mean reversion | Long-only rolling z-score entries and explicit exits. |
| Regime-adaptive ensemble | Momentum, short reversal, RSI gating, and inverse-volatility allocation. |
| Rolling conformal ML | Rolling histogram gradient boosting with split-conformal classification sets; trades only when the negative class is excluded. |

“Modern” does not mean “deepest model wins.” June 2026 evidence comparing financial time-series foundation models found that their gains over random-walk benchmarks remained small and sparse, despite strong relative model rankings. Edgecraft therefore treats ML as one candidate and puts most of its sophistication into leakage control, economic execution, uncertainty, and multiple-testing correction. See [Pretrained Time-Series Foundation Models for Financial Return Forecasting](https://arxiv.org/abs/2606.27100) and [Multivariate Financial Forecasting using the Chronos Time Series Foundation Models](https://arxiv.org/abs/2605.21504).

## Quick start

Requirements: Python 3.11–3.14 and `uv`. Node is only used for a JavaScript syntax check.

```bash
make install
```

Start the application:

```bash
make dev
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Start with **Synthetic demo** for a deterministic run. Switch to **Yahoo market** to download adjusted historical data into `data/cache/`.

For a terminal-only smoke run:

```bash
make demo
```

The UI uses browser-native JavaScript and SVG, so there is no frontend package install or compilation step.

## Proper research workflow

1. **State the hypothesis first.** Fix the universe, observable information, rebalance schedule, costs, benchmark, and pass/fail criteria before inspecting results.
2. **Run a plain baseline.** Compare conditional DCA against plain DCA with identical deposits. Compare tactical strategies against buy-and-hold or an economically appropriate benchmark.
3. **Keep time causal.** Signals at session close execute no earlier than the next session open. Rolling ML trains only on labels known at that timestamp.
4. **Separate discovery and judgment.** Tune on earlier windows, lock the specification, then judge it on untouched walk-forward windows. Add an embargo at least as long as overlapping labels when extending the suite to multi-day prediction targets.
5. **Model implementation.** Increase spread and slippage, test missing sessions, inspect turnover, and verify that a signal becomes an order and then a fill rather than assuming execution.
6. **Penalize searching.** Record every trial. DSR adjusts Sharpe for multiple testing and non-normal returns; CSCV/PBO estimates how often in-sample winners degrade out of sample.
7. **Prefer plateaus.** A broad region of acceptable parameters is more credible than one isolated optimum.
8. **Advance in stages.** Synthetic test → historical backtest → shadow signals → human-confirmed tiny orders → bounded automation.

The suite follows the core warnings in Bailey et al.'s [Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253) and Bailey & López de Prado's [Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551).

## Architecture

```text
frontend/                     dependency-free experiment terminal
  app.js                      methodology guide, configuration, interactive SVG run explorer, metrics, fill audit
src/edgecraft/
  api.py                      FastAPI endpoints and built-UI serving
  data.py                     adjusted market data, cache, synthetic regimes
  engine.py                   causal event loop and execution simulator
  indicators.py               reusable point-in-time features
  metrics.py                  return/risk, bootstrap, DSR, CSCV/PBO
  models.py                   typed experiment and execution contracts
  research.py                 experiment matrix orchestration/serialization
  strategies.py               strategy interface and included candidates
tests/                        data, causality, engine, research, API tests
scripts/demo.py               deterministic terminal demo
```

## API

- `GET /api/health` — liveness and version
- `GET /api/strategies` — UI-ready strategy/parameter schemas
- `POST /api/backtests?data_source=synthetic|market` — run an experiment matrix
- `GET /docs` — generated OpenAPI explorer while FastAPI is running

The request body is defined by `BacktestRequest` in `src/edgecraft/models.py`. The UI is a complete client and is the easiest way to construct requests.

## Validation and limitations

Run all checks:

```bash
make test
make lint
```

Current scope is daily, long-only stocks/ETFs. The Yahoo downloader is convenient research data, not a point-in-time fundamentals database or exchange-grade feed. Adjusted bars reduce corporate-action discontinuities but do not eliminate survivorship bias in a hand-selected present-day universe. There is no borrow model, taxes, market impact curve, intraday order book, delisting-return database, or live broker integration.

The conformal classifier offers finite-sample coverage only under its exchangeability assumptions; financial regime shifts can violate them. DSR and PBO are diagnostics, not certificates of future profitability. Treat every displayed result as a hypothesis to challenge.

## Extending safely

Add strategies by subclassing `Strategy`, implementing `generate`, registering the class in `STRATEGIES`, and adding a UI schema to `STRATEGY_SCHEMAS`. Strategy code receives history only through the current close and returns intentions; only the engine may create fills.

Before adding fundamental, analyst, or alternative data, require point-in-time timestamps and revision history. A current snapshot joined to historical prices is look-ahead contamination.
