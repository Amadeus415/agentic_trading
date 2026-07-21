# Roadmap to an institutional agentic investment manager

## Current assessment

Edgecraft is a strong autonomous trading prototype, but it is not yet a
demonstrated hedge fund or a proven source of market-beating returns.

**Current rating: 3 out of 5 as an investment-manager system.**

The control and execution architecture is considerably stronger than the
investment edge:

| Dimension | Score | Assessment |
| --- | ---: | --- |
| Deterministic risk controls | 4.8/5 | Strong separation between model proposals, single-use authority, and broker reconciliation |
| Software and testing | 4.6/5 | Typed implementation, causal execution, immutable decisions, recovery tests, and clear failures |
| Research methodology | 3/5 | Walk-forward testing, cost stress, PBO, Deflated Sharpe, point-in-time features, and benchmark accounting are sound foundations |
| Demonstrated alpha | 0.5/5 | Current research evidence fails promotion |
| Institutional operations | 2/5 | Daily automation and auditable operations exist, but there is no independent fund infrastructure or long live track record |

Alpha and institutional readiness receive the greatest weight in the overall
rating. Edgecraft should continue to be described as an experimental,
policy-gated portfolio manager until both improve materially.

No system can promise to outperform the S&P 500. The objective must be to build
the strongest possible evidence for repeatable, risk-adjusted, after-cost alpha
while making failure and uncertainty visible.

## Current evidence

A real-market research run through July 17, 2026 covered 2,901 sessions of SPY
and QQQ data. It produced:

- value-tilted DCA annualized return of 16.89%;
- plain DCA annualized return of 16.53%;
- an apparent advantage of approximately 0.37 percentage points annually;
- Probability of Backtest Overfitting of 100%;
- Deflated Sharpe probability of 40.7%, below the 95% promotion requirement;
- a walk-forward fold win rate of 42.1%;
- failed walk-forward and multiple-testing promotion gates.

The small historical return advantage is not reliable alpha evidence. The
comparison also does not establish S&P 500 outperformance because the benchmark
is plain DCA across the same SPY/QQQ universe rather than a clean S&P 500
total-return series with identical cash flows, costs, taxes, and measurement
periods.

The first tiny-live order exposed a model-output schema failure after the broker
had already filled the order. The broker order, fill, position, cash, and buying
power were independently reconciled to the local ledger. The run was closed by
the strict incident-reconciliation command without weakening the kill switch.
The regression is now covered by exact terminal recovery and uncertain-state
tests, and model-authored broker output has been narrowed to a minimal receipt
that Python binds to the immutable permitted order.

The current release also adds:

- immutable decision packets containing the mandate, policy, model and prompt
  versions, structured evidence, external context, and market snapshot;
- completed-session full-universe market intelligence with checksums;
- broad, freshness-aware web, regulatory, and social-search context;
- independent reconciliation of every broker order ID;
- transaction-cost analysis against the decision price; and
- cash-flow-matched agent, S&P 500 proxy, and strategic baseline books.

These capabilities make the experiment measurable and operable. They do not
turn one live fill into evidence of alpha.

The external base rate is demanding. S&P Dow Jones Indices reported that 79% of
active large-cap U.S. equity funds underperformed the S&P 500 in 2025. Recent
LLM-agent research also finds that most agents struggle to beat simple
buy-and-hold baselines and that financial-research accuracy remains inadequate
for unsupervised high-stakes decisions.

## Target operating principle

Use agents to propose hypotheses, collect timestamped evidence, implement
experiments, challenge leakage, and explain results. Use deterministic code to
calculate signals, allocate risk, authorize orders, and promote strategies.

Adding more agent personalities does not create alpha by itself. Agent debate
belongs before the typed policy boundary, and no persuasive narrative should be
able to bypass an adverse statistical result or risk limit.

## Priority 1: stabilize the current system — completed at canary scale

The schema failure is captured as a regression, the broker boundary now returns
a narrow receipt, deterministic recovery covers known terminal and uncertain
states, and the affected live run has been independently reconciled. Continue
to hold authority at tiny-canary size while accumulating operational evidence.

## Priority 2: define what success means

“Beat the S&P 500” must become an explicit, versioned research contract.

At minimum, define:

- an investable S&P 500 total-return benchmark;
- identical deposits and valuation timestamps for candidate and benchmark;
- gross and net time-weighted return;
- after-cost and, where applicable, after-tax excess return;
- alpha, beta, information ratio, Sortino ratio, and maximum drawdown;
- turnover, slippage, liquidity, and capacity;
- acceptable underperformance periods and capital-loss limits;
- the minimum number of independent decisions and live observation period.

A levered strategy with a higher return and much larger drawdown is not
automatically better. Success should mean durable net alpha at an explicitly
bounded level of risk.

## Priority 3: build institutional point-in-time data

Yahoo adjusted OHLCV is useful for prototypes but insufficient for an
institutional research process. Create a versioned research lake containing:

- point-in-time universe membership;
- delistings and corporate actions;
- filings with acceptance and public-availability timestamps;
- point-in-time fundamentals;
- earnings, estimates, revisions, and surprises;
- news and transcripts with original publication timestamps;
- bid, ask, spread, volume, and liquidity histories;
- borrow availability and fees before any short strategy is considered;
- observation time, effective time, source, revision, and checksum for every
  feature.

Research must be reproducible from immutable snapshots. A feature cannot enter
a decision before it was genuinely knowable and tradable.

## Priority 4: create an autonomous research factory

Build a governed loop that can generate and reject ideas without contaminating
the final evaluation:

1. A research agent writes a frozen hypothesis, economic rationale, universe,
   benchmark, expected horizon, costs, and pass/fail rule.
2. An implementation agent creates the feature and strategy using only approved
   point-in-time data.
3. An adversarial validation agent searches for leakage, survivorship bias,
   unstable parameters, hidden beta, and unrealistic execution.
4. Deterministic evaluation runs purged and embargoed validation, cost stress,
   placebo tests, ablations, parameter stability, PBO, and Deflated Sharpe.
5. A promotion service accepts or rejects the candidate without model
   discretion.
6. Every attempted experiment, including failures, enters an immutable trial
   registry so multiple-testing adjustments reflect the real search process.

Keep an untouched final lockbox period. For LLM-driven historical decisions,
prevent model-memory contamination by replaying timestamped source packets and
testing whether conclusions depend on facts or narratives published later.

## Priority 5: develop independent alpha sleeves

Do not optimize only the existing RSI and moving-average parameters. Research
several economically distinct, low-correlation sleeves, such as:

- cross-sectional value, quality, and momentum;
- analyst estimate revisions and earnings surprises;
- filing and corporate-event signals;
- liquid macro trend and defensive volatility;
- short-horizon liquidity or reversal signals where execution evidence
  supports them;
- agent-assisted extraction of structured facts from filings and transcripts.

Each sleeve must survive independent validation and make a measurable marginal
contribution after controlling for market, size, value, quality, momentum, and
other known factor exposures.

## Priority 6: add institutional portfolio construction

Separate signal generation from position sizing. The portfolio layer should:

- combine calibrated expected returns and uncertainty;
- estimate covariance and factor exposure;
- constrain beta, sectors, factors, single names, groups, and liquidity;
- model turnover, spread, market impact, taxes, and capacity;
- optimize expected net alpha rather than raw forecast strength;
- attribute realized performance to beta, factors, selection, timing, and
  execution;
- shrink or disable strategies automatically when drift or degradation exceeds
  a deterministic limit.

Long-short trading, leverage, options, or less-liquid assets should remain out
of scope until the long-only research and operational processes have a durable
record.

## Priority 7: strengthen production operations

Move from a capable single-machine workflow toward an independently controlled
production system:

- immutable, reviewed deployment artifacts;
- separate research, staging, paper, and live environments;
- independent pre-trade and post-trade risk services;
- broker abstraction and deterministic broker simulators;
- durable queues, idempotency, restart recovery, and disaster recovery;
- transaction-cost analysis comparing decision, arrival, review, fill, and
  subsequent prices;
- continuous reconciliation of broker, custodian, and internal books;
- model, prompt, data, policy, and code versioning on every decision;
- alerting, incident ownership, change approval, and periodic access reviews;
- tested kill switches that do not depend on the reasoning model.

The existing permit, reconciliation, audit, and kill-switch architecture should
be preserved as the foundation.

## Priority 8: establish a credible live experiment

Operate three contemporaneous portfolios with identical cash flows:

1. passive S&P 500 benchmark;
2. deterministic non-LLM strategy;
3. agent-assisted candidate strategy.

Progress through historical replay, shadow, paper, and tiny-live stages. Freeze
the rules for each evaluation period and do not silently remove unsuccessful
trials or change the benchmark.

Require at least 12–24 months of live evidence and enough independent decisions
to evaluate behavior across more than one market condition. Report all returns
net of realistic costs, including failed decisions, holds, downtime, rejected
orders, and cash drag.

## Example promotion standard

Exact thresholds are governance decisions, but a serious initial standard could
require:

- Deflated Sharpe probability of at least 95%;
- Probability of Backtest Overfitting no greater than 20%;
- positive net alpha in a clear majority of out-of-sample folds;
- a positive information ratio at an explicitly bounded beta;
- acceptable drawdown and stress performance;
- stability across parameters, subperiods, assets, and regimes;
- survival under materially higher transaction costs;
- sufficient capacity at multiples of intended capital;
- successful shadow and paper histories with no unresolved reconciliation;
- a pre-registered tiny-live evaluation completed without changing the rules.

Passing these gates would justify a controlled capital increase. It would not
guarantee future outperformance.

## Priority 9: build the fund only after proving the manager

A hedge fund is a legal and operational organization, not only a trading
program. Before accepting outside capital, obtain qualified legal, tax, and
compliance advice and establish, as applicable:

- fund, general-partner, and investment-adviser entities;
- adviser registration or exemption analysis;
- private-placement, subscription, and governing documents;
- qualified custody and appropriate brokerage arrangements;
- independent fund administration, valuation, audit, and tax reporting;
- investor eligibility, onboarding, AML, and recordkeeping procedures;
- cybersecurity, privacy, compliance, and business-continuity programs;
- independently calculated investor performance and reporting.

The research and live record should be investable, reproducible, and externally
verifiable before capital raising begins.

## Suggested sequence

### Next 30 days

- Accumulate unchanged daily operational and three-book performance evidence.
- Create the experiment registry and formal promotion contract.
- Add point-in-time fundamentals and corporate-event features from licensed or
  primary-source data.
- Keep live capital at canary size.

### Days 31–90

- Introduce point-in-time data contracts and immutable snapshots.
- Add purged validation, contamination tests, factor attribution, and capacity
  analysis.
- Develop three economically independent research sleeves.
- Launch the three-way shadow evaluation.

### Months 3–12

- Graduate only passing strategies to paper and tiny-live portfolios.
- Build portfolio optimization, drift detection, transaction-cost analysis, and
  stronger production infrastructure.
- Publish a complete internal monthly performance and incident report.

### Months 12–24

- Accumulate an unchanged, independently measured live record.
- Increase capital only through predetermined gates.
- Begin legal and operational fund formation only if net alpha, reliability,
  capacity, and drawdown evidence remain credible.

## What not to do next

- Do not increase live authority because one backtest has a higher ending value.
- Do not optimize the current parameters until they pass.
- Do not treat model confidence or agent consensus as statistical evidence.
- Do not add leverage, shorting, or options to compensate for weak alpha.
- Do not hide failed experiments, holds, incidents, or cash drag.
- Do not describe the system as market-beating until independently measured
  evidence supports that statement.

## References

- [SPIVA U.S. Year-End 2025](https://www.spglobal.com/spdji/en/spiva/article/spiva-us/)
- [The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)
- [The Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)
- [Finance Agent Benchmark](https://arxiv.org/abs/2508.00828)
- [StockBench](https://arxiv.org/abs/2510.02209)
- [SEC: Starting a Private Fund](https://www.sec.gov/about/starting-private-fund)
- [FINRA: Supervision and Control Practices for Algorithmic Trading](https://www.finra.org/rules-guidance/notices/15-09)
