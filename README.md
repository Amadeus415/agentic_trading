# Edgecraft

**Can an autonomous fund powered by a Codex subscription beat the S&P 500?**

That's the experiment. Edgecraft starts with $1,000 of simulated money, researches public markets, takes short-term positions, and learns from the results. The ambition is aggressive growth: find opportunities often, act quickly, and improve the process over time.

All trades are paper trades. There is no real-money execution path.

## How it works

Three loops run one fund:

1. **Trade.** Codex researches stocks, crypto, and prediction markets. It explains each idea, estimates its probability, and gives it a target, a stop, and a 4–72 hour horizon. Python fetches prices, sizes positions, checks limits, and records simulated fills.
2. **Manage.** An hourly Python monitor checks existing positions and enforces exits. It needs no model call.
3. **Learn.** After seven days or 20 additional closed trades, Codex reviews outcomes and proposes changes. New strategy versions keep separate records. Validated experiments start small; untested prompt changes stay in shadow with no capital.

Codex does the research. Code owns the money math. An append-only SQLite ledger remembers what happened, including losses. The initial bankroll is deposited once.

Being active means searching broadly and taking worthwhile opportunities. More trades alone don't make a better fund: every entry must clear estimated costs, and cash is a valid result when nothing qualifies.

## Try it

You need Python 3.11–3.14, [uv](https://docs.astral.sh/uv/), and Node.js 22+ for the dashboard.

```bash
make install
make validate
make fund-init
make fund-context
cd dashboard && npm ci && cd ..
make dashboard
```

Open [localhost:3000](http://localhost:3000). The dashboard shows fund value against SPY (an S&P 500 ETF), positions, trades, decision evidence, and learning progress. An empty ledger starts empty; setup does not invent trades.

```bash
make fund-show         # current book and history
make fund-verify       # replay the accounting and verify the audit chain
make fund-report-file  # refresh trade results and learning status
```

For unattended trading, use a separate clean runtime checkout and the existing Codex schedules. Read [Operations](docs/OPERATIONS.md) for setup and [the trading instructions](docs/CODEX_SCHEDULED_TASK.md) for the exact cycle. Research uses ChatGPT-authenticated Codex, subject to subscription limits; the monitor is ordinary local Python. Local scheduled tasks require the host and app to be available ([OpenAI documentation](https://learn.chatgpt.com/docs/automations?surface=app)).

## What is proven so far?

The accounting, audit trail, public-data adapters, scheduled trading path, and read-only dashboard are implemented. They are useful engineering foundations. **A profitable trading edge is not established.**

The September 4, 2026 runtime audit found $916.66 NAV, 16 closed trades, and −$5.21 average after-cost profit per trade. That is a dated observation, not a live scoreboard. Use the dashboard for the current book.

The learning loop can persist new research versions and allocate small paper sleeves using recorded outcomes. It does not yet establish that a prompt change caused better returns. Shadow promotion, stronger experiment validation, and realistic execution need more work. The dashboard's SPY comparison uses completed daily price closes; dividends are excluded, so it is not a total-return performance claim.

Read [the assessment and next steps](docs/PLAN.md) for the remaining gaps and concrete success criteria.

## The code is organized around the fund

| Location | Responsibility |
| --- | --- |
| `src/edgecraft/paper_fund.py` | Money, positions, limits, and immutable ledger |
| `src/edgecraft/marketdata/`, `sizing.py`, `monitor.py` | Public prices, position size, and exits |
| `src/edgecraft/attribution.py`, `evolution.py`, `allocator.py` | Results, experiments, and strategy budgets |
| `playbooks/` | Four starting strategies and their research prompts |
| `scripts/` | Scheduled trading and local monitoring |
| `dashboard/` | Read-only view of the fund |

The optional research lab contains backtests and walk-forward tools. It supports research; it does not run a second fund. Detailed contracts live in [Design](docs/DESIGN.md) and [Accounting](docs/FUND_ACCOUNTING.md).

## Where this could go

The project should become an open, reproducible demonstration of an agent operating a persistent system: making decisions, measuring outcomes, and testing improvements. That is already a stronger engineering story than claiming an AI can pick stocks.

Real money is a later, separate project decision. First build a long forward record with realistic costs, controlled drawdowns, and consistent outperformance against a dividend-aware S&P benchmark. Then evaluate a broker's paper environment and a tiny, explicitly authorized live pilot. A profitable simulation does not automatically authorize real orders.

Source is public; ledgers, generated research, caches, and credentials stay out of Git. [Apache 2.0](LICENSE) · [Security](SECURITY.md).
