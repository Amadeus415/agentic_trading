# Prediction-market experiment: completion and evidence

Implemented: separate prediction-only mandate and bankroll, explicit venue fee model, public Polymarket/Kalshi adapters, book-mid marks and depth-aware fills, bounded scanner, three language-research playbooks, exact code provenance, revision lineage, first-funded-contract Brier/CLV scoring, v1 archive, retirement, and a read-only fund switcher.

History is preserved: original ledger rows and images remain, original playbooks are archived, and the old implementation is tagged `v1-multi-asset`. Historical flat-bps accounting still replays. New versions cannot inherit the old fund's returns.

The prediction runtime was deployed on October 17, 2026 using [Operations](OPERATIONS.md). V1 was retired flat at $1,020.41 with all 96 cycles preserved; v2 received its independent one-time $1,000 deposit. No trading cycle was forced during deployment. A complete private state backup and consistent SQLite backup were taken before cutover. Initial API checks encountered a local certificate trust error. On October 17, read-only checks succeeded with normal TLS verification, including public listings and usable venue books/fees. Some empty books were correctly rejected. Live access must still be verified from the deployed runtime before resuming schedules.

Forward evidence still required: sustained after-cost results, Brier improvement over the market across independent events, dense enough pre-settlement quotes for useful CLV, conservative execution checks, and longer date-aligned SPY comparisons. Threshold/date ladders and mutually exclusive sets need verified rules and exhaustive membership; the scanner deliberately does not infer those structures from titles. No validated asset-price reference model exists, so those contracts are excluded.

Profitable LLM alpha, structural arbitrage, causal improvement from code changes, and real-money readiness are unproven.
