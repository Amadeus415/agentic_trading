# Prediction-market fund design

One operating path: Claude researches and forecasts, deterministic Python sizes and applies, a code-only control fund sets the bar, and a read-only dashboard explains the ledger.

## Separate eras, one ledger

The v1 fund `edgecraft-aggressive` retains its immutable mandate and full multi-asset record. `edgecraft-predictions` receives a separate, one-time $1,000 deposit. This is a new experiment, not a reset of the old record or a claim that the combined bankroll grew. `fund-retire` appends an idempotent retirement event to a flat fund; subsequent new cycles are rejected while exact historical replays and verification remain available.

Historical asset enums, accounting, and flat-bps fees remain for replay. The prediction mandate explicitly selects `prediction_taker_v1`; adding a prediction-only fund never changes an old fund's fee model. The old stock research lab is removed from the active package and preserved by the `v1-multi-asset` Git tag. Original playbooks live under `history/v1-multi-asset/playbooks`. Read-only stock price helpers remain for historical analysis and benchmark data, not the new tradable universe.

## Research and discovery

`fund-scan` lists open binary markets on both venues in four horizon windows (under a day, 1–3 days, 3–7 days, longer), so near-dated contracts cannot crowd out the rest. It drops stock/crypto price bets, missing deadlines, resolutions outside the one-year window, and listings without a usable two-sided quote, all before spending a book request.

Rank is `attention / days to resolution`, where attention falls slowly with 24-hour volume. It favors contracts that resolve soon (capital turns over) and that few traders watch (prices adjust slowly). Liquidity is a constraint, not the goal: a side needs only `min_depth_usd` at the best ask and a spread under 10¢. Each candidate reports its executable ask, fee, `return_if_wins`, `annualized_if_wins`, and the favorite-bias probability. `catalysts` lists candidates resolving within 48 hours. Rank is research priority, never evidence of alpha.

`event_flags` finds mutually exclusive outcomes (Polymarket negative-risk events, Kalshi events marked mutually exclusive) whose YES bids sum above $1. Buying NO on every listed outcome then pays at least n − 1 for less than that, whether or not the list is exhaustive. `cross_venue_flags` pairs similar YES questions whose books do not overlap. Neither claims executable arbitrage until the rules are read.

## Quotes and simulated execution

Instrument IDs are `polymarket:<Gamma market ID>:YES|NO` and `kalshi:<ticker>:YES|NO`. Public adapters cache immutable observed quotes; `fund-run --code-owned-quotes` replaces advisory marks with those code-fetched records. Open quotes need a valid two-sided book. Marks use the best bid/ask midpoint. Fills consume displayed asks for buys and bids for sells, refusing insufficient size rather than filling at the midpoint.

Polymarket selects CTF token IDs for v1 and position IDs for v2. Unknown protocols or fee schedules fail closed. Closed markets are settled only when the resolution status confirms resolution and the purchased outcome is exactly 0 or 1. Kalshi requires final `settled` status and a binary result. Closed, disputed, void, or otherwise unsupported resolution states stop marking rather than inventing payouts.

The prediction mandate uses recorded taker parameters: quantity × rate × [price × (1−price)]^exponent, rounded upward to the quoted fee quantum. Kalshi quadratic rates incorporate the public series multiplier; unsupported fee types are rejected. Polymarket reads `feesEnabled` and `feeSchedule`. Kalshi uses a conservative cent ceiling; Polymarket uses a conservative five-decimal ceiling. This cash-fee simulation does not model venue-specific share deductions or fractional fee carry. Applying a nonlinear fee curve to the VWAP rather than individual matches can overestimate fees. Entry fees and an expected early-exit fee enter the after-cost edge check. Official binary settlements charge no trading fee.

Reference contracts: [Polymarket books](https://docs.polymarket.com/market-data/prices-order-books), [Polymarket market fees](https://docs.polymarket.com/market-data/market-details), [Kalshi books](https://docs.kalshi.com/api-reference/market/get-market-orderbook), [Kalshi fees](https://kalshi.com/docs/kalshi-fee-schedule.pdf). Adapter fixtures validate parsing; live access must be checked before operation. TLS or denied-access failures are terminal research blockers, never cash-hold evidence.

## Sizing

Python turns each researched belief into a quantity in three steps:

1. **Trust.** The belief is shrunk toward the market midpoint: `market + λ × (p_win − market)`, with λ measured per playbook from its forecast log ([how the fund learns](EVOLUTION.md)). Unmeasured playbooks use the 0.35 prior.
2. **Velocity.** The after-cost edge must clear `min_annualized_return` (30%) over the stated horizon, and entries are funded in order of annualized return, so scarce cash goes to the fastest-compounding edges.
3. **Kelly.** Fractional Kelly (half in the research fund) on the cost including fees, inside the 25% position cap (with 5% headroom so later entries' spread cannot push an earlier position over it), the 35% shared-driver cap, sleeve budgets, displayed depth, and the mandate. After the book walk, the edge must still clear the entry fee, an expected early-exit fee (losers at the stop, winners at the target; settlement is free), and exit slippage.

## The code-only control fund

`edgecraft-baseline` (config `examples/fund.mandate.baseline.json`) shares the mandate and ledger but has no model in the loop. The five-minute monitor calls `fund-baseline`, which scans at most once per `baseline_interval_minutes` and writes a cycle only when it buys:

- **Favorite bias.** Contracts priced between 80¢ and 98.5¢ that resolve within 21 days, bought when `logistic(γ × logit(mid))` exceeds the ask plus fees. γ starts at 1.15 and is refit from settled markets.
- **Exclusive NO baskets.** Equal NO quantity on every leg of a flagged event when the executable asks still lock in at least 1¢ per basket, inside the shared-event cap.

Its sizing uses quarter Kelly, a 10% position cap, and a 20% event cap. Its report is `state/fund-report-edgecraft-baseline.json`, and the dashboard's fund selector shows it beside the research fund.

## Risk and learning

The fund buys cash-backed outcomes, never naked shorts. Python fits cash, turnover, depth, and drawdown limits inside the 1× gross/net mandate. `p_win` means probability that the purchased outcome settles at $1. Target and invalidation prices govern optional early exits. The monitor enforces the original opening time and declared horizon (up to 8,760 hours), stops, targets, and official settlement.

Every cycle carries the exact Git revision and current uncommitted/untracked status. `fund-lineage` groups consecutive revisions, labelling old deployment-time attribution inferred. The report includes first-funded-contract Brier improvement against the entry market, sampled CLV, and the forecast skill described in [how the fund learns](EVOLUTION.md).

Position P&L can cross revision boundaries. Revision segments, Brier scores, trust, and drift are measurements, not proof of causality or a durable edge. Sampled depth can disappear before a real fill, settlement can be delayed, and the favorite-bias prior is an assumption until settled markets confirm it.
