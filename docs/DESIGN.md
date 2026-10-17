# Prediction-market fund design

One operating path: Codex researches, deterministic Python applies, and a read-only dashboard explains the ledger.

## Separate eras, one ledger

The v1 fund `edgecraft-aggressive` retains its immutable mandate and full multi-asset record. `edgecraft-predictions` receives a separate, one-time $1,000 deposit. This is a new experiment, not a reset of the old record or a claim that the combined bankroll grew. `fund-retire` appends an idempotent retirement event to a flat fund; subsequent new cycles are rejected while exact historical replays and verification remain available.

Historical asset enums, accounting, and flat-bps fees remain for replay. The prediction mandate explicitly selects `prediction_taker_v1`; adding a prediction-only fund never changes an old fund's fee model. The old stock research lab is removed from the active package and preserved by the `v1-multi-asset` Git tag. Original playbooks live under `history/v1-multi-asset/playbooks`. Read-only stock price helpers remain for historical analysis and benchmark data, not the new tradable universe.

## Research and discovery

`fund-scan` reads bounded pages from both venues and alternates venue candidates before spending its book-fetch budget. It excludes obvious stock/crypto price bets, missing deadlines, and resolutions outside the one-year window. A subsequent semantic research check must exclude price bets missed by the conservative text filter. Spread and displayed best-ask depth determine research rank. Neither rank nor matching question text establishes alpha.

The consistency scanner flags same-market complementary purchase costs below $1 and cross-venue YES bid/ask gaps on similar questions. It does not infer exhaustive outcome sets or threshold/date relationships from text alone. Research can inspect those relationships, but must establish identical rules, dates, timezones, sources, and exclusions. No cross-venue atomic execution or automatic arbitrage is claimed.

## Quotes and simulated execution

Instrument IDs are `polymarket:<Gamma market ID>:YES|NO` and `kalshi:<ticker>:YES|NO`. Public adapters cache immutable observed quotes; `fund-run --code-owned-quotes` replaces advisory marks with those code-fetched records. Open quotes need a valid two-sided book. Marks use the best bid/ask midpoint. Fills consume displayed asks for buys and bids for sells, refusing insufficient size rather than filling at the midpoint.

Polymarket selects CTF token IDs for v1 and position IDs for v2. Unknown protocols or fee schedules fail closed. Closed markets are settled only when the resolution status confirms resolution and the purchased outcome is exactly 0 or 1. Kalshi requires final `settled` status and a binary result. Closed, disputed, void, or otherwise unsupported resolution states stop marking rather than inventing payouts.

The prediction mandate uses recorded taker parameters: quantity × rate × [price × (1−price)]^exponent, rounded upward to the quoted fee quantum. Kalshi quadratic rates incorporate the public series multiplier; unsupported fee types are rejected. Polymarket reads `feesEnabled` and `feeSchedule`. Kalshi uses a conservative cent ceiling; Polymarket uses a conservative five-decimal ceiling. This cash-fee simulation does not model venue-specific share deductions or fractional fee carry. Applying a nonlinear fee curve to the VWAP rather than individual matches can overestimate fees. Entry fees and a conservative worst-price exit-fee reserve enter the after-cost edge check. Official binary settlements charge no trading fee.

Reference contracts: [Polymarket books](https://docs.polymarket.com/market-data/prices-order-books), [Polymarket market fees](https://docs.polymarket.com/market-data/market-details), [Kalshi books](https://docs.kalshi.com/api-reference/market/get-market-orderbook), [Kalshi fees](https://kalshi.com/docs/kalshi-fee-schedule.pdf). Adapter fixtures validate parsing; live access must be checked before operation. TLS or denied-access failures are terminal research blockers, never cash-hold evidence.

## Risk and learning

The fund buys cash-backed outcomes, never naked shorts. Half Kelly, 25% single-position and 35% driver ceilings sit inside a 1× gross/net mandate; Python also fits cash, turnover, depth, and drawdown limits. `p_win` means probability that the purchased outcome settles at $1. Target and invalidation prices govern optional early exits. The monitor enforces the original opening time and declared horizon (up to 8,760 hours), stops, targets, and official settlement.

Every cycle carries the exact Git revision and current uncommitted/untracked status. `fund-lineage` groups consecutive revisions, labelling old deployment-time attribution inferred. The report includes first-funded-contract Brier improvement against the entry market and sampled CLV, grouped by playbook and revision. Profitable early exits are not binary outcomes. CLV requires an observed later pre-settlement quote; missing observations stay null. Daily-or-10-closed-position reviews create separate research versions with their own forward evidence.

Position P&L can cross revision boundaries. Revision segments, Brier scores, and sparse CLV are measurements, not proof of causality or a durable edge. Sampled depth can disappear before a real fill, settlement can be delayed, and the model's coverage and probabilities remain unproven assumptions.
