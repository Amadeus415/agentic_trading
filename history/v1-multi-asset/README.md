# Era v1: multi-asset paper fund (August 22 – October 5, 2026)

This is the frozen record of Edgecraft's first era. In v1, one Codex researcher traded stocks, crypto, and Polymarket contracts from a single $1,000 simulated bankroll. The ledger fund `edgecraft-aggressive` is still in the append-only database and still verifies, and is retired explicitly during the v2 deployment; this archive alone does not freeze the runtime. The code is preserved at git tag [`v1-multi-asset`](https://github.com/Amadeus415/agentic_trading/tree/v1-multi-asset).

All fills were simulated. The samples are small, so read these numbers as evidence for a direction to take, not as proof of an edge.

![v1 verified simulated fund progress](fund-progress.svg)

## Final result

| | |
| --- | --- |
| Cycles | 96 (21 trade, 75 hold) |
| Final NAV | **$1,020.41** (+2.04%) |
| Peak NAV / drawdown at freeze | $1,189.88 / 14.2% |
| Closed round trips | 22, 11 winners |
| After-cost expectancy | +$0.93 per trade; 95% interval −$19.21 to +$21.06 |
| SPY over the same sparse window | +1.53% price return, 5 recorded quotes, dividends excluded |
| Hash chain and accounting replay | verified |

## Why v2 trades prediction markets only

**1. Stocks lost money in every view of the data.**

| Asset class | Realized round trips | Realized P&L after cost | Scored research ideas | Idea expectancy | Idea profit factor |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stock | 12 (5 won) | **−$41.28** | 87 | −$2.27 | 0.26 |
| Crypto | 4 (3 won) | +$17.52 | 58 | +$0.60 | 1.94 |
| Prediction | 6 (3 won) | **+$44.16** | 33 | +$5.95 | 1.25 |

Stocks made up more than half the trades and all of the class-level losses. LLM research on liquid equities is competing against the most efficient prices in the world, with costs and stale public quotes working against it. We found no evidence that the model had an edge there.

**2. The prediction wins and losses came from different kinds of edge.**

| Contract | Result | What kind of bet it was |
| --- | ---: | --- |
| Sept Fed 25-bp hike YES | **+$99.36** | News reaction: repriced after a sticky PCE print |
| BTC above $82k this week YES | **+$104.61** | Crypto direction |
| Brazil runoff NO at 0.93 | **+$25.39** | Resolution reading: near-certain outcome |
| BTC touches $80k by Aug 31 YES | **−$160.24** | Crypto direction: a longshot sized at 16% of NAV |
| BTC above $76k / $78k at noon | −$24.97 | Crypto direction, same-day expiry |

The Fed and Brazil trades used what LLMs are actually good at: reading news and settlement rules quickly and literally. The BTC-threshold contracts were crypto price speculation in a prediction-market wrapper. Their net was −$80.60, and they produced the single largest loss. In v2, contracts whose outcome is just an asset price get priced by a deterministic reference model, not by LLM conviction.

**3. The goal had structural limits.** A 72-hour horizon cap and stock-session schedules were designed for equities. They kept the fund from holding contracts to resolution, which is where prediction-market payoffs are known and settle at 0 or 1.

## What v1 got wrong about provenance

Every v1 cycle recorded `edgecraft_version: "1.0.0"` and no git commit. Its performance therefore can't be attributed to a specific code change. v2 records the exact source revision on every cycle and keeps an append-only [changelog](../../CHANGELOG.md) of why each change was made. The [lineage report](../README.md) attributes v1 cycles to commits by deploy time and labels that attribution *inferred*.

## Files

- `fund-progress.svg`: the verified NAV chart published by the runtime on October 4, 2026.
- `results.json`: the summary, every realized round trip, calibration, and per-asset-class cuts. It was exported read-only from the runtime `fund-report.json`. Private research evidence and ledger rows stay out of Git.
