# Edgecraft

Edgecraft is a local, point-in-time stock-strategy research and orchestration toolkit. It combines an event-driven Python backtester, a React experiment UI, realistic next-session execution, adversarial validation, portfolio diagnostics, deterministic trade risk gates, an idempotent audit ledger, and a Robinhood MCP handoff protocol.

It is not investment advice and it deliberately does not hold broker credentials or submit broker requests itself. The authenticated orchestrator owns the Robinhood MCP session; Edgecraft produces evidence, checks a proposal, and defines the exact review/reconcile workflow. Backtests can be wrong even when the code is correct.

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
- Rolling train/select/test walk-forward validation with non-overlapping out-of-sample windows
- Canonical portfolio/quote/target/policy contracts for an orchestration agent
- Long-only equity proposals with quote freshness, whitelist, cash, concentration, daily-spend, and research-promotion gates
- SQLite proposal/event ledger with deterministic idempotency keys
- Robinhood review → authorized placement → reconciliation handoff
- One `edgecraft` CLI for the complete research-to-execution workflow
- Market and portfolio-risk diagnostics: returns, RSI, trend, volatility, drawdown, beta, correlations, VaR, expected shortfall, and component risk

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

## Orchestrator CLI

```bash
# Check the official Robinhood MCP connection and local ledger.
edgecraft health

# Run research and rolling out-of-sample selection.
edgecraft backtest --config examples/research.json --data-source market
edgecraft backtest --config examples/research.json --data-source market --cost-multiplier 5
edgecraft walk-forward --config examples/research.json --data-source market
edgecraft evidence --backtest base.json --walk-forward walk.json --cost-stress stress.json --strategy value_tilted_dca
edgecraft market --symbols SPY,QQQ --benchmark SPY

# Analyze a fresh MCP-derived account snapshot.
edgecraft portfolio --snapshot snapshot.json
edgecraft portfolio-risk --snapshot snapshot.json --benchmark SPY

# Produce a non-executable shadow proposal and persist its idempotency key.
edgecraft propose \
  --snapshot snapshot.json \
  --quotes quotes.json \
  --targets examples/targets.json \
  --policy examples/policy.shadow.json \
  --strategy value_tilted_dca \
  --mode shadow

# Inspect the machine-readable MCP contract and audit state.
edgecraft protocol
edgecraft ledger
```

The snapshot and quote files must be created from fresh Robinhood MCP results. Never copy the redacted examples into a live call. See [docs/ORCHESTRATOR.md](docs/ORCHESTRATOR.md) for the full agent contract, promotion gates, live-mode procedure, and failure behavior.

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
  walkforward.py              rolling train/select/test validation
  execution_models.py         portfolio, quote, policy, evidence, proposal contracts
  portfolio.py                allocation, P&L, and concentration diagnostics
  risk.py                     deterministic proposal construction and pre-trade gates
  ledger.py                   SQLite idempotency and execution audit log
  orchestration.py            Robinhood MCP two-phase handoff
  analytics.py                market and portfolio historical-risk diagnostics
  promotion.py                artifact-derived live-promotion evidence
  cli.py                      single command surface for agents and humans
tests/                        data, causality, research, API, CLI, and execution tests
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

Live proposals remain long-only equities, dollar-notional, and bounded by a checked-in policy. Options, shorting, leverage, margin, bracket orders, and autonomous strategy promotion are outside the execution scope. A proposal being approved means “safe enough to send to Robinhood's review tool,” not “profitable” and not “already placed.”

The conformal classifier offers finite-sample coverage only under its exchangeability assumptions; financial regime shifts can violate them. DSR and PBO are diagnostics, not certificates of future profitability. Treat every displayed result as a hypothesis to challenge.

## Extending safely

Add strategies by subclassing `Strategy`, implementing `generate`, registering the class in `STRATEGIES`, and adding a UI schema to `STRATEGY_SCHEMAS`. Strategy code receives history only through the current close and returns intentions; only the engine may create fills.

Before adding fundamental, analyst, or alternative data, require point-in-time timestamps and revision history. A current snapshot joined to historical prices is look-ahead contamination.
