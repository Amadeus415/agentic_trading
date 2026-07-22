# Building Edgecraft from durable investment principles

## Executive decision

Edgecraft should not try to imitate the secret portfolio of any famous fund. It
should imitate the parts of their operating systems that survive outside their
original scale, access, and market:

- Berkshire's owner mindset, patience, and candor about mistakes;
- Bridgewater's conversion of hypotheses into explicit, testable rules;
- AQR's use of diversified factors rather than one heroic forecast;
- Two Sigma and D. E. Shaw's treatment of data, time, and reproducibility as
  production code;
- Yale's long horizon and insistence that diversification matters;
- venture capital's search for asymmetric, power-law upside, paired with staged
  conviction rather than equal certainty about every company.

The simple investment thesis is:

> **Own liquid public companies capable of long-duration compounding. Add only
> when business quality, expectations, trend, and portfolio fit agree. Pay less
> attention to activity than to evidence. Hold cash when the edge is weak, and
> learn from every decision against a frozen benchmark.**

The system can increase the odds of a good outcome by surviving, controlling
costs, avoiding weak evidence, and learning honestly. It cannot make
profitability inevitable. Any claim that this design *will* beat the market
would be inconsistent with the research standard the design itself imposes.

## What “successful” means

The owner wants profitable autonomous trading, but profitability is an outcome,
not a software acceptance test. Edgecraft therefore has four separate success
levels:

1. **Operational integrity:** the scheduled cycle runs once, uses fresh data,
   obeys the mandate, and reaches a known terminal broker state.
2. **Decision integrity:** the thesis is testable, all influential evidence is
   retained, alternatives and falsifiers are explicit, and no untrusted source
   is promoted into fact.
3. **Research validity:** a frozen strategy survives point-in-time walk-forward
   tests, costs, parameter perturbation, Deflated Sharpe Ratio, and probability
   of backtest overfitting checks. Bailey and colleagues show why selecting from
   many backtests can produce impressive in-sample results that deteriorate
   out-of-sample ([paper](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659)).
4. **Economic evidence:** over a long, predeclared live or shadow period, the
   agent beats both a cash-flow-matched SPY sleeve and the fixed strategic sleeve
   after estimated costs, without unacceptable drawdown or operational gaps.

Levels one and two can be engineered. Level three can reject bad ideas. Only
time and real outcomes can establish level four.

## The transferable lessons

### Berkshire Hathaway: behave like an owner

Berkshire's annual communications emphasize long-term growth in intrinsic value,
an ownership mindset, disciplined capital allocation, and reporting both good
and bad developments rather than marketing optimism
([2024 letter](https://www.berkshirehathaway.com/letters/2024ltr.pdf),
[2025 letter](https://www.berkshirehathaway.com/letters/2025ltr.pdf)).

Transfer into Edgecraft:

- Analyze a stock as a fractional ownership interest in a business.
- State the economic mechanism: what can compound, why it can persist, what is
  already embedded in price, and what would prove the thesis wrong.
- Make the expected horizon explicit. A 126-day fundamental thesis should not
  be abandoned because of one weak session.
- Treat cash as a valid position. The daily budget is a ceiling, not a quota.
- Record mistakes in the same durable form as wins.

Do not copy concentrated Berkshire-sized bets. Edgecraft has less information,
less access, a short track record, and a very different capital base.

### Bridgewater: make reasoning explicit and preserve survival

Bridgewater describes turning investment principles into algorithms, testing
them through many historical cases, combining uncorrelated return sources, and
optimizing return for a desired risk rather than maximizing raw return. It also
emphasizes that one catastrophic period can remove an investor from the game
([Bridgewater's account](https://www.bridgewater.com/our-founder)). Its AIA Labs
description is especially relevant: clean bitemporal data, an explicit corpus of
reasoning, and feedback are the foundations beneath an “artificial investor,”
not optional polish ([AIA Labs](https://www.bridgewater.com/aia-labs)).

Transfer into Edgecraft:

- Models propose; deterministic code authorizes.
- Every thesis names its mechanism, horizon, falsifiers, and evidence.
- Independent signals should agree for different reasons. Three copies of the
  same news story are one signal, not three.
- The portfolio and kill switch are more important than any forecast.
- The next decision receives compact prior theses and measured outcomes, never
  an opaque summary of “what worked.”

Do not copy leveraged risk parity or global macro positioning into a long-only
Robinhood account without the instruments, data, execution, and risk staff that
make those approaches coherent.

### AQR: combine evidence and charge every strategy for friction

AQR's published work finds value and momentum premia across markets and notes
that they diversify one another
([Value and Momentum Everywhere](https://www.aqr.com/insights/research/journal-article/value-and-momentum-everywhere)).
Its quality research defines quality through profitability, growth, safety, and
management-related measures rather than a compelling narrative
([Quality Minus Junk](https://www.aqr.com/insights/research/working-paper/quality-minus-junk)).
Its work on low-volatility strategies also shows that apparent returns can be
substantially reduced by turnover and transaction costs
([Limits to the Low-Volatility Anomaly](https://www.aqr.com/Insights/Research/Journal-Article/The-Limits-to-Arbitrage-and-the-Low-Volatility-Anomaly)).

Transfer into Edgecraft:

- Use a small ensemble: quality, valuation/expectations, medium-term trend and
  revisions, plus risk/portfolio fit.
- Keep every factor visible. Do not hide a discretionary conclusion behind a
  composite score.
- Prefer signals that work across neighboring parameters and multiple periods.
- Model spread, slippage, turnover, taxes where applicable, and cash drag.
- Never call a historical anomaly a guaranteed source of alpha.

Edgecraft currently has robust price/trend/risk features. Point-in-time quality,
valuation, and revision features remain an important data gap; the model may use
fresh structured fundamentals as cited evidence, but the project should not
pretend that price momentum is a complete multi-factor process.

### Two Sigma and D. E. Shaw: data is part of the strategy

Two Sigma describes scientific, data-driven investing across diversified
strategies ([investment philosophy](https://www.twosigma.com/businesses/investment-management/))
and explains that treating data like code means versioning datasets and
infrastructure, testing them, measuring coverage, and making research replayable
([Treating Data as Code](https://www.twosigma.com/articles/treating-data-as-code-at-two-sigma/)).
D. E. Shaw describes a rigorous research- and data-driven continuum from
systematic to discretionary investing
([investment management](https://www.deshaw.com/what-we-do/investment-management));
its public library explicitly calls versioned time-series data necessary to
avoid using information from a later time in an earlier decision
([library](https://www.deshaw.com/library)).

Transfer into Edgecraft:

- Preserve source and retrieval timestamps separately.
- Content-hash market snapshots, decision memory, prompts, and normalized
  evidence.
- Never overwrite a prior decision packet.
- Keep data collectors behind typed interfaces and use deterministic fakes.
- Promote only features that can be reconstructed point in time.

Do not imitate high-frequency or proprietary alternative-data strategies. A
scheduled Codex process through Robinhood MCP has neither the latency nor the
execution economics for that game.

### Yale: win on horizon and discipline, not prediction frequency

Yale attributes its program to long-term focus, independent thinking, and
people, and measures success over decades rather than days
([2023 community letter](https://investments.yale.edu/wp-content/uploads/2024/09/Matt-2023-Community-Letter.pdf)).
Its endowment material argues that disciplined diversification contributed to
its long-term record even though diversification can disappoint in individual
crises ([2019 report](https://investments.yale.edu/wp-content/uploads/2024/10/2019YaleEndowment.pdf)).

Transfer into Edgecraft:

- Use the schedule for regular observation, not forced daily opinion changes.
- Judge long-duration theses on their declared horizon.
- Diversify economic drivers, not merely ticker count.
- Make benchmark discipline permanent.

Do not copy Yale's private-market allocation. Edgecraft lacks manager access,
illiquidity tolerance, institutional legal structure, and private valuations.

### Venture capital: use power-law thinking as a bounded lens

Venture returns are highly skewed. Andreessen Horowitz presents portfolio data
where a small fraction of investments produced most returns
([Babe Ruth effect](https://a16z.com/performance-data-and-the-babe-ruth-effect-in-venture-capital/)).
Sequoia emphasizes unique founder insight, large potential markets, long-term
partnership, and removing artificial holding-period constraints
([seed investing](https://sequoiacap.com/article/sequoia-and-seed-investing/),
[patient capital](https://sequoiacap.com/article/the-sequoia-fund-patient-capital-for-building-enduring-companies/)).

Transfer into Edgecraft:

- Look for public companies with large addressable markets, improving unit
  economics, durable advantages, and management capable of reinvestment.
- Start with small exposure while evidence is incomplete. Add only when public,
  point-in-time evidence confirms milestones.
- Do not sell a genuine compounder merely to lock in a small gain; reassess the
  thesis and opportunity cost.
- Keep speculative “venture-like” names inside explicit group and position caps.

Power-law thinking does **not** mean buying every exciting story. Public prices
already contain expectations, losses are real, and a long-only account cannot
recreate private ownership terms or board access.

## The four-lens decision

Every eligible finalist should be evaluated through four independent lenses.
No single lens authorizes an order.

| Lens | Core question | Examples of point-in-time evidence | Failure mode |
| --- | --- | --- | --- |
| Business quality | Can the business compound value? | margins, free cash flow, balance sheet, retention, returns on capital | confusing revenue growth with economic quality |
| Expectations | What must already be true at this price? | valuation history, peer multiples, embedded growth, estimate dispersion | buying a great company at any price |
| Trend and revisions | Is new information being incorporated favorably? | 6- and 3-month momentum, earnings revisions, guidance changes, breadth | chasing a one-day move or crowded narrative |
| Portfolio fit | Does this improve the whole account? | factor/sector exposure, correlation, drawdown, liquidity, current holdings | treating a good company as a good-sized position |

The decision contract then requires:

- one causal thesis mechanism;
- an expected horizon in days;
- concrete falsifiers;
- at least three alternatives: best candidate, strategic baseline, and cash;
- evidence IDs for every allocation;
- prior run IDs only when prior outcomes materially affect the conclusion;
- fresh final broker truth before the deterministic gate.

Confidence is not a feeling. It should reflect agreement among independent
lenses, source quality, freshness, uncertainty, and historical calibration.

## Giving the model useful context over time

More tokens are not automatically more intelligence. The model needs a compact,
ordered information set:

1. **Owner mandate:** objective, universe, cadence, benchmark, hard budget, and
   strategic weights.
2. **Deterministic market snapshot:** completed-session prices, trend, risk,
   liquidity, breadth, and checksum for the complete universe.
3. **Broker truth:** the dedicated agentic account, holdings, cash, open orders,
   fills, P&L, current tradability, and fresh quotes.
4. **Fundamental evidence:** normalized, timestamped facts for no more than a few
   finalists.
5. **External context:** a bounded packet with source quality and evidence role.
6. **Decision memory:** recent mechanisms, horizons, falsifiers, allocations,
   next-period benchmark-relative outcomes, and aggregate cash-flow-matched
   performance.
7. **Risk policy:** the code-enforced constraints the model cannot change.

The new `decision_memory.py` packet is deliberately small. It prevents two bad
extremes: forgetting every prior thesis, and dumping a private raw ledger into a
prompt. Its checksum and exact contents are stored in the immutable decision
packet.

Short-horizon feedback is included because it is observable, not because it is
conclusive. A 126-day thesis cannot be declared right or wrong by its next-day
return. The outcome helps detect repeated adverse selection; the falsifier and
horizon govern the thesis review.

## External context and the alpha research ladder

### Evidence hierarchy

| Quality | Sources | Allowed use |
| --- | --- | --- |
| Primary fact | SEC filings, issuer releases, official economic data, broker records | establish timestamped facts |
| Primary claim | designated executive/issuer channel, earnings call, investor presentation | represent what management said; still verify outcomes |
| Secondary analysis | reputable reporting, industry research, expert analysis | supply context and counterarguments with corroboration |
| Unverified sentiment | podcasts, investor posts, Bluesky/X/Reddit/Stocktwits | generate questions, detect crowding, or lower confidence |

The SEC says issuer social channels can carry company announcements when
investors have been told which channels will be used, but Regulation FD still
applies ([SEC guidance](https://www.sec.gov/newsroom/press-releases/2013-2013-51htm)).
The SEC has also charged social-media manipulation schemes
([example](https://www.sec.gov/newsroom/press-releases/2022-221)). Therefore a
CEO post can be a management claim, while an unauthenticated repost remains
unverified sentiment. Neither becomes a policy override.

### Practical source plan

**Integrated now**

- Robinhood MCP for account, order, quote, and tradability truth. Robinhood
  explicitly supports Codex and warns that autonomous agent trades can occur
  without per-trade confirmation and can lose the entire investment
  ([official overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/)).
- Adjusted completed daily history for comparable universe-wide features.
- Browserbase discovery/fetch, SEC EDGAR when CIKs are configured, and bounded
  Bluesky context.
- Source labels: `primary`, `secondary`, and `unverified`, paired with `fact`,
  `management_claim`, `analysis`, or `sentiment`.

**Build next, in shadow**

- Point-in-time SEC XBRL fundamentals for quality and valuation.
- Issuer-domain allowlists and designated investor-relations feeds.
- Bitemporal analyst-estimate/revision data from a licensed provider.
- Official macro vintages from FRED, BLS, BEA, and the Federal Reserve.
- Transcript ingestion only with a licensed source and retained publication
  timestamps.
- Named expert/investor feeds only after identity, timestamp, licensing, and
  manipulation controls exist.

**Do not promote directly to live sizing**

- a podcast recommendation;
- a famous investor's disclosed position without its price, mandate, hedge, and
  reporting lag;
- raw tweet/post volume;
- scraped content with unclear rights or edited timestamps;
- a feature selected because it improved one backtest.

New context earns influence through a fixed ladder:

```text
collect and hash
  -> label source quality
  -> shadow feature only
  -> point-in-time replay
  -> walk-forward test with costs
  -> manipulation and outage tests
  -> predeclared canary budget
  -> compare against frozen baseline
  -> retain, cap, or remove
```

## The scheduled Robinhood pipeline

```text
Codex scheduled task
  -> health and readiness
  -> cycle lock and remaining hard budget
  -> completed-session market intelligence
  -> prior decision and benchmark memory
  -> focused external context
  -> read-only Robinhood observation
  -> structured thesis, alternatives, horizon, and falsifiers
  -> immutable decision packet
  -> deterministic portfolio and risk gate
  -> fresh Robinhood preflight
  -> policy fingerprint re-check
  -> expiring single-use exact-order permit
  -> one placement call
  -> independent reconciliation
  -> evaluation and append-only audit
```

The [Robinhood Agentic Trading overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/)
confirms the MCP endpoint can expose account data and place trades only in the
dedicated Agentic account. Edgecraft adds a narrower software authority layer on
top: the scheduler may initiate the run, but neither the scheduler nor Codex can
mint a permit without passing deterministic controls.

An unknown or partial broker result is not a reason to retry placement. Edgecraft
must read exact broker state once, record the incident, and halt if identity or
terminal state remains uncertain.

## How the current code reflects the thesis

| Principle | Implementation |
| --- | --- |
| Explicit owner intent | `Mandate` fixes budget, cadence, universe, benchmark, strategic weights, model, and live mode |
| Full-universe comparison | `intelligence.py` captures completed-session trend, risk, liquidity, regime, and checksum |
| Testable thesis | `WeeklyDecision` v3 records mechanism, horizon, and falsifiers |
| Learning without narrative drift | `decision_memory.py` links prior immutable decisions to next-period cash-flow-matched excess returns |
| Source hierarchy | `ContextSource` records source quality and evidence role; social defaults to unverified sentiment |
| Evidence lineage | allocation evidence IDs and context source IDs are validated before proposal creation |
| Independent authority | `risk.py`, policy digest, preflight, and one-use permits remain outside the model |
| Honest comparison | `evaluation.py` maintains agent, SPY, and strategic sleeves with equal contributions and costs |
| Broker truth | `codex_runtime.py` uses Robinhood MCP for fresh observation, exact placement, and reconciliation |
| Replayable audit | the decision packet retains mandate, policy, context, market snapshot, memory, observation, model, and prompt version |

## Why this design can improve the odds

It has five plausible advantages:

1. **Horizon advantage:** a small owner can hold through noise without monthly
   redemptions or career-risk pressure.
2. **Attention consistency:** the agent can run the same checklist every market
   day without fatigue, while still choosing hold.
3. **Process memory:** facts, decisions, and outcomes are retained exactly rather
   than reconstructed after the result is known.
4. **Capacity fit:** tiny fractional-share orders avoid the capacity constraints
   that make some public anomalies difficult for large funds.
5. **Error containment:** small budgets, long-only authority, group caps,
   freshness gates, one-use permits, and reconciliation limit the damage of a bad
   model conclusion or tool failure.

These advantages are only useful if trading frequency remains low enough that
costs and noise do not dominate, and if the project obtains genuinely
point-in-time fundamental data. The language model is not itself an edge; it is
an adaptable research interface inside a measured system.

## What would invalidate the project thesis

The owner should reduce or stop live capital if any of these persist:

- the agent underperforms both SPY and the strategic sleeve after a meaningful,
  frozen evaluation period and estimated costs;
- decisions show no calibration between confidence and outcomes;
- new context increases turnover but not out-of-sample performance;
- source timestamps or historical revisions cannot be reconstructed;
- operational incidents create unknown broker states;
- alpha disappears when one theme, time period, or parameter is removed;
- the strategy's advantage is explained entirely by concentrated beta;
- the process requires repeated exceptions to its own risk rules.

## Build order from here

### Now: preserve the clean control plane

- Keep the new decision memory and structured thesis fields.
- Keep social optional and bounded.
- Continue daily cash-flow-matched evaluation.
- Do not increase the live budget based on a handful of trades.

### Next: complete the four-lens dataset

1. Add point-in-time SEC XBRL quality and valuation features.
2. Add deterministic factor components and missing-data flags rather than a more
   complicated opaque ranker.
3. Add thesis reviews at their declared horizon, not only next-period outcomes.
4. Measure confidence calibration and attribution by signal family.

### Then: run frozen shadow challengers

- baseline: fixed strategic contributions;
- challenger A: transparent quality + value + momentum;
- challenger B: the same factors plus bounded textual context;
- challenger C: the current agent process.

Predeclare the comparison window and costs. Do not edit a challenger after
seeing its test-period result. Promotion requires operational reliability,
out-of-sample evidence, drawdown tolerance, and a capital ceiling. Failure means
retire the challenger, not reinterpret the benchmark.

## Bottom line

The realistic “best of venture, hedge funds, and quant firms” is not a cloned
portfolio. It is an institution-like operating system for a very small account:
patient ownership, asymmetric opportunity, diversified evidence, point-in-time
data, explicit falsification, hard risk, exact execution, and honest feedback.

That system is understandable enough to audit, simple enough to operate, and
skeptical enough to improve. Those properties can raise the probability of
long-run success. They are also the reason Edgecraft will know when its thesis is
not working.
