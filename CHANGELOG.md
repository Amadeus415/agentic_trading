# Changelog

Changes to what agents face or how they are scored bump the benchmark version. Runs are compared only within a version.

## 0.1.0 · 2026-10-27

The first benchmark version.

- Agents are Claude models in Claude Code, headless, one sandboxed session per agent four times a day, with a $1,000 paper account and a 28-day window.
- The exchange fills market orders against live Polymarket and Kalshi books with venue taker fees, whole shares, a 25% position cap, and accounts valued at the best bid.
- Two arms: evolving (the workspace persists and can be rewritten) and frozen (reset to the seed every session).
- Code-only baselines: favorites and random. Cash and the S&P 500 are shown for context.
- Metrics: return, max drawdown, after-fee edge per dollar, forecast skill against the market price, inference cost and self-modification, with cluster-bootstrap intervals over events.

Before this, the project was a human-designed paper fund; see `history/README.md` and the `pilot` tag.
