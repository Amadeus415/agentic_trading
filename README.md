<div align="center">

# EDGECRAFT

### An autonomous paper fund pursuing $1,000 → $100,000

Edgecraft is a fully autonomous paper-trading fund with one job: turn $1,000 of fake money into $100,000 without ever touching a real brokerage account. Several times per weekday an AI agent (Codex) scans public markets, manages a short-term multi-position stock/crypto/prediction book, and records 4–72 hour falsifiable hypotheses before proposing a buy, sell, short, cover, or hold. Deterministic Python decides whether that proposal is allowed. Accepted trades land in an append-only SQLite ledger with the full evidence and decision journal; rejected ones are recorded too, and nothing can be edited or deleted afterward.

The design principle is simple: **models may propose; typed policy and risk engines authorize.** The agent cannot bypass accounting checks, inject cash, reset losses, or place a real order — the codebase has no live execution path at all.

[![CI](https://github.com/Amadeus415/agentic_trading/actions/workflows/ci.yml/badge.svg)](https://github.com/Amadeus415/agentic_trading/actions/workflows/ci.yml)
[![Python 3.11–3.14](https://img.shields.io/badge/python-3.11%E2%80%933.14-0b1220?logo=python&logoColor=white)](pyproject.toml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-0b1220.svg)](LICENSE)
[![Money: fake](https://img.shields.io/badge/money-100%25%20fake-22c55e)](docs/CODEX_SCHEDULED_TASK.md)

**[Starting prompt](docs/FUND_STARTING_PROMPT.md)** · **[Scheduled Codex task](docs/CODEX_SCHEDULED_TASK.md)** · **[Accounting contract](docs/FUND_ACCOUNTING.md)** · **[Research lab](#research-lab)**

</div>

![Edgecraft paper fund progress](assets/fund-progress.svg)

The chart above is regenerated from the verified append-only ledger after every scheduled
paper cycle. It is a public project snapshot, not a brokerage statement or investment claim.

> [!IMPORTANT]
> Edgecraft is an engineering experiment, not investment advice. The active fund is incapable of placing a real order: it has no live mode, broker adapter, credentials, or execution permit.

## The whole system

```mermaid
flowchart LR
    C["Codex scans public markets + reads fund memory"] --> D["Hypotheses + sourced portfolio decision"]
    D --> G{"Typed accounting and risk gates"}
    G -->|Reject| A["Append-only audit"]
    G -->|Pass| P["Simulated fill"]
    P --> B["Persistent compounding paper book"]
    B --> A
```

In one sentence: Codex proposes a short-term sourced portfolio decision; `paper_fund.py` applies it to a persistent $1,000 fake-money ledger.

The bankroll is deposited once. There is no daily contribution and no reset. The explicit research objective is to compound $1,000 into $100,000 over ten years—an aggressive 100x target requiring about 58.5% annualized returns, not a promise. The fund takes long and short positions in stocks, native crypto, and binary prediction contracts. It may name any syntactically valid instrument; there is no symbol whitelist. Every trade still needs fresh sourced prices, cited evidence, valid inventory, and room inside the checked-in risk envelope. Scheduled cycles cannot rest in 100% cash.

The active book is `edgecraft-aggressive` (`examples/fund.mandate.aggressive.json`): a high-tempo, short-term trader that searches each UTC session, manages several independent 4–72 hour positions when strong ideas exist, can run full-size shorts, and cuts broken theses fast. Compounded NAV is the objective; idle cash is a miss. The original conservative book (`edgecraft-1k`) stays frozen and verifiable at `state/edgecraft-fund.db`.

Current envelope:

| Control | Limit |
|:--|--:|
| Initial fake cash | $1,000 once |
| Gross exposure | max($1,500, 3.00 × earned NAV) |
| Absolute net exposure | max($1,000, 2.00 × earned NAV) |
| Short exposure | max($500, 1.00 × earned NAV) |
| One position | 60% of NAV |
| Turnover per cycle | max($1,000, 4.00 × earned NAV) |
| Orders per cycle | 30 |
| Drawdown gate | 50% |
| Simulated fee / slippage | 5 / 10 bps |

The dollar values are bootstrap floors; limits scale only after the fund earns a higher NAV, never through deposits. Codex chooses the instruments, direction, sizing, and whether to trade; code prevents broken accounting, stale or unsupported inputs, and risk outside the experiment. The growth target cannot override those controls.

## Run it

Requirements: Python 3.11–3.14 and [uv](https://docs.astral.sh/uv/).

```bash
make install
make validate
make fund-init
make fund-context
```

`fund-context` prints the authoritative cash, positions, P&L, target progress, capital stage, mandate, exact JSON schema, and a compact ledger-derived brain. The brain shows recent theses, later NAV direction, costs, winning/losing exits, current unrealized P&L, rejections, and the latest hypothesis for each instrument. It is feedback, not causal performance attribution.

To exercise all three asset classes with static example data and a disposable ledger:

```bash
tmp_ledger="$(mktemp -d)/edgecraft-example.db"
uv run edgecraft fund-init \
  --config examples/fund.mandate.json \
  --ledger "$tmp_ledger"
uv run edgecraft fund-run \
  --config examples/fund.mandate.json \
  --input examples/fund-cycle.starting.example.json \
  --ledger "$tmp_ledger"
uv run edgecraft fund-verify \
  --config examples/fund.mandate.json \
  --ledger "$tmp_ledger"
```

The example is executable fixture data, not a current market decision.

## Start and operate the paper book

The first run uses the [starting prompt](docs/FUND_STARTING_PROMPT.md). It gives Codex the empty $1,000 book and requires a researched opening trade. Later runs use the [scheduled task](docs/CODEX_SCHEDULED_TASK.md) to mark every open position, revisit the thesis, and trade or hold without human approval. A scheduled hold is legal only while positions are open.

Print the current session key, then write the packet there:

```bash
uv run edgecraft fund-cycle-key
```

```text
state/fund-inputs/YYYY-MM-DD-session-us-open.json
```

Then the fixed apply path runs:

```bash
./scripts/run_scheduled_cycle.sh
```

The script refuses a missing or non-current input, verifies the existing hash chain before applying anything, runs the deterministic paper cycle, and verifies the entire accounting history again. It contains no broker command.

Inspect the experiment at any time:

```bash
make fund-show
make fund-verify
uv run edgecraft fund-show --history --events
```

CLI defaults are the active aggressive mandate ledger (`state/edgecraft-aggressive.db`). Pass `--config` / `--ledger` only to inspect another book.

| Command | Job |
|:--|:--|
| `fund-validate` | Parse the checked-in mandate |
| `fund-init` | Capitalize the fund exactly once |
| `fund-context` | Agent packet: state, brain, JSON schema |
| `fund-run` | Apply one researched decision |
| `fund-show` | Inspect the book (`make fund-show` includes `--history`) |
| `fund-cycle` | One cycle packet (`--audit` for event gaps) |
| `fund-verify` | Hash-chain and accounting replay (`make fund-verify`) |

## Dashboard

Read-only Next.js UI for NAV, positions, journals, hypotheses, the fund brain, and paper fills over `state/edgecraft-aggressive.db`.

```bash
make dashboard
# or: cd dashboard && npm install && npm run dev
```

See [dashboard/README.md](dashboard/README.md).

## Accounting model

- Positions have signed fractional quantities: positive is long, negative is short.
- `buy` cannot cover, `sell` cannot open a short, `short` cannot reduce a long, and `cover` cannot open a long.
- NAV is cash plus signed marked positions. Gross exposure uses absolute market values.
- Fees and adverse slippage are charged on every simulated fill.
- Prediction contracts settle only from a sourced terminal quote of exactly `0` or `1`.
- A cycle is atomic. A rejected input changes nothing.
- Replaying the same cycle and payload is a no-op; changing a used cycle key is rejected.
- The exact normalized decision, evidence, quotes, fills, state, request digest, and chained events are stored in SQLite. Immutable-table triggers reject update and delete operations.

See [the accounting contract](docs/FUND_ACCOUNTING.md) for formulas, the decision packet, and invariants.

## Repository map

```text
src/edgecraft/
├── paper_fund.py           # typed models, accounting, risk, SQLite audit ledger
├── fund_brain.py           # compact outcomes, position hypotheses, and lessons
├── schedule.py             # UTC session slots and cycle keys
├── cli.py                  # fund commands plus optional research-lab commands
├── growth.py               # deterministic growth objective and capital stages
└── observability.py        # structured JSON logging

examples/fund.mandate.aggressive.json       # active $1,000 aggressive mandate
examples/fund.mandate.json                  # retired conservative fixture
examples/fund-cycle.starting.example.json   # executable three-market fixture
scripts/run_scheduled_cycle.sh              # fixed session paper apply path
scripts/deny_broker_tools.py                # fail-closed Codex fence against broker tools
tests/test_paper_fund.py                    # accounting and failure invariants
docs/                                       # accounting contract and Codex prompts
```

## Research lab

Causal backtest, strategy, cost-stress, and walk-forward tools live in the optional `lab` extra. They are research inputs, not the paper fund's source of cash or execution authority.

```bash
uv sync --extra lab   # or: make install, which includes the lab via --extra dev
make demo
make validate-lab
uv run edgecraft strategies
uv run edgecraft backtest --config examples/research.json --data-source synthetic
uv run edgecraft walk-forward \
  --config examples/research.json \
  --data-source synthetic \
  --train-sessions 504 \
  --test-sessions 126
```

Options are intentionally not modeled yet. Adding them requires explicit
contracts for multipliers, expiry, exercise/assignment, spreads, liquidity, and
worst-case loss; Edgecraft will not pretend an option is ordinary stock.

## Security and privacy

Generated ledgers, inputs, caches, and logs stay out of Git. Never include credentials, private account data, form contents, or unnecessary personal information in evidence packets. Use public URLs and concise provenance. Report vulnerabilities through [SECURITY.md](SECURITY.md).

Edgecraft is released under the [Apache License 2.0](LICENSE).
