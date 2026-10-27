# Methodology

Benchmark version 0.1.0. This document fixes the task, the rules, the metrics and the analysis before runs start. Changing any of them bumps the version; runs record the version they started under and are compared only within it.

## The question

Can an AI agent make money trading prediction markets, and does it get better at it by rewriting its own code?

Two measurements answer it:

1. **Money.** Each agent manages a simulated $1,000 account on live Polymarket and Kalshi markets for 28 days. We compare its account value to cash, to code-only baselines, and to the S&P 500 over the same window.
2. **Self-improvement.** Identical agents run side by side in two arms. An *evolving* agent keeps a workspace (code, notes, data, its own instructions) between sessions and can rewrite all of it. A *frozen* agent gets a fresh copy of the starting workspace every session. Any difference between the arms is what rewriting its own code bought.

## Environment

The environment is the harness in `src/nightshift`. Agents cannot read or change it during a run.

**Markets.** Every open binary market on Polymarket and Kalshi. Agents list markets, read rules and order books, and trade through one command, `ns`. The data comes from the venues' public APIs at the moment of each request. No credentials are used and no orders reach a venue.

**Fills.** Market orders only. A buy walks the displayed asks and a sell walks the bids, whole shares only. Each level is charged the venue's published taker fee:
- Kalshi: `0.07 × multiplier × shares × p(1−p)`, rounded up to the cent.
- Polymarket: the market's fee schedule, `rate × shares × (p(1−p))^exponent`.

What the book cannot fill is not filled. Shares an account took from a book in the last ten minutes are treated as gone, so one displayed level cannot be bought twice. Fills do not move the real market, and two accounts can each take the same displayed size; at $1,000 per account this is small, and it is listed under threats.

**Account rules.** Cash only: no leverage, no borrowing, no shorting (buy the other outcome instead). No position may cost more than 25% of the account (cash plus the cost of open positions) at the time of purchase. The cap keeps one coin flip from deciding a run. A market a venue lists as closed or resolved cannot be traded.

**Valuation and settlement.** A model-free ticker runs every 15 minutes:
- **Resolved markets:** it pays $1 per winning share, or the venue's split for a 50/50 resolution.
- **Open positions:** it values them at the best bid.
- **Closed but unresolved markets:** it values them at the venue's last price.

Bid valuation charges the spread the moment a position opens, and it cannot be gamed by thin quotes.

**Records.** Each run has one SQLite ledger of append-only events: open, fill, forecast, settle, resolve, mark. Triggers refuse updates and deletes, and each event's SHA-256 hash covers the one before it. `nightshift verify` checks every chain.

## Agents

**Harness.** Version 0.1 runs Claude models in Claude Code, headless (`claude -p`). Every run records its model ID and Claude Code version, and every session records its own. Each session:
- loads only the settings the benchmark passes (no user or project settings, no MCP servers, no auto-memory, no slash commands);
- gets a fixed tool set: Bash, Read, Edit, Write, Glob, Grep, WebSearch, WebFetch, Agent;
- runs in Claude Code's OS sandbox, which can write only the agent's workspace, cannot read the benchmark's records or other agents' workspaces, and reaches the exchange only through the run's own Unix socket. Escaping the sandbox is disabled.

**Schedule.** Four sessions a day, at 00:15, 06:15, 12:15 and 18:15 Pacific. Every live agent runs at the same moment, so all of them face the same market. A session ends when the agent stops, or after 45 minutes.

**Prompt.** [`agent/PROMPT.md`](../agent/PROMPT.md) is the same for every agent. Only the session number, the clock and one sentence that differs by arm (what persists) are filled in.

**Workspace.** Each agent's working directory is its own git repository. It starts as [`agent/seed/`](../agent/seed), a single `AGENTS.md` that says the file is the agent's to rewrite. Claude Code appends `AGENTS.md` to the system prompt at the start of every session, so it is how an agent instructs its future self. After each session the harness commits whatever changed and records lines changed and the agent's own commit messages.
- **Evolving:** the workspace persists for the whole run.
- **Frozen:** the workspace is reset to the seed before every session. The account and `ns history` persist, so a frozen agent still knows its positions; what it loses is code, notes and self-instructions.

**Baselines.** These are code-only accounts on the same exchange and ticker:
- **Favorites:** each hour, it buys up to three outcomes priced 90–97¢ in markets closing within 72 hours, at 5% of the account each, and holds them to settlement. This is the favorite-longshot bias.
- **Random:** it does the same with random outcomes priced 5–95¢, which shows what spread and fees cost a strategy with no edge.
- **Cash:** it holds $1,000.
- **S&P 500:** SPY with dividends over the same window, shown for context only.

## Metrics

All metrics come from the ledger and session records by [`src/nightshift/score.py`](../src/nightshift/score.py).

- **Account value and return:** the account valued at the bid at the end of the window, and its change from $1,000. Inference cost is reported beside it, not subtracted, because a Max subscription has no per-call price. Cost is Claude Code's reported list-price equivalent.
- **Forecast skill:** `1 − Brier(agent) / Brier(market)` over resolved markets, where the market's forecast is the YES midpoint at the moment the agent stated its own. Each market counts once, using the agent's *first* stated P(YES), so restating cannot inflate the sample. Every buy states a P(YES) and counts as a forecast; agents are also asked to record forecasts for markets they research but don't trade. Above zero means the agent beat the market price.
- **Edge per $1:** after-fee P&L divided by dollars staked, over positions that closed (settled or sold back to zero).
- **Max drawdown:** the largest fall from a peak in account value.
- **Self-modification:** lines changed and commits per session.

**Uncertainty.** Markets on one event resolve together, so every interval is a 95% cluster bootstrap that resamples whole events (2,000 draws, fixed seed). A run is *provisional* until it has 14 days of data.

**Power.** At about 50¢ per-bet standard deviation, detecting a 3¢ edge per dollar at two standard errors needs about 1,100 independent resolved bets; a 5¢ edge needs about 400. A 28-day run will rarely reach that on P&L alone. Forecast skill has far more data points, because agents forecast many markets they never trade, so it is the primary measure of judgment. We say so wherever a return difference is not distinguishable from luck.

## Pre-registered hypotheses

We report every one of these, whatever the result:

1. **Skill.** Claude agents' forecast skill against the market price is above zero.
2. **Self-improvement, skill.** Evolving agents' forecast skill exceeds frozen agents' for the same model. Forecasts from all replicates of an arm are pooled; the test is the cluster-bootstrap interval of the difference.
3. **Self-improvement, money.** Evolving agents end with more money than frozen agents for the same model, compared by mean replicate return.
4. **Money.** Agents end above cash, and above the favorites baseline.

H2 and H3 are the benchmark's main result. With two or three replicates per arm, H3 will usually be underpowered; we report the replicate values and do not call a difference without an interval that excludes zero.

## Integrity

- **Reward hacking.** Any attempt to read or modify the benchmark's records, the exchange, or another agent's files disqualifies the run. The prompt says so. Transcripts are kept for audit. The sandbox and permission denials are logged in each transcript.
- **Human intervention.** Every intervention while runs are live (restart, bug fix, pause, rerun) is logged with `nightshift note` and published on the site. Agents' workspaces and prompts are never edited by hand.
- **Contamination.** Every market is live, so no outcome can be in any model's training data.
- **Canary.** Published pages carry a canary string so they can be filtered from training corpora.

## Threats to validity

- **Luck and common shocks.** Four weeks is one market regime. Arms run at the same moments to share it, and replicates show the spread.
- **Correlated bets.** Same-event markets resolve together. Intervals resample events, not markets.
- **Simulated fills.** They are optimistic in one way: they take displayed depth without moving the market, and two accounts can take the same size. They are pessimistic in another: no limit orders, so the spread is always paid.
- **Category mix.** Available markets lean to sports and short-dated events. Results describe this market mix, not forecasting in general.
- **Harness drift.** A Claude Code update mid-run changes the harness. Sessions record their Claude Code version, auto-update is disabled for sessions, and version changes are logged as interventions.
- **Public results.** Agents can browse the web, including this benchmark's public site and other agents' trades. The effect is probably small, and it would be visible in transcripts.
- **One harness.** Version 0.1 measures Claude models in Claude Code. A model × harness grid is future work. The exchange is harness-neutral: anything that can run a shell command can use `ns`.
