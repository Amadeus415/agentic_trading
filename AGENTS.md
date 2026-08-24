# Edgecraft Agent Instructions

## Mission

Build a highly active, understandable autonomous **paper hedge fund**. Edgecraft
starts with exactly $1,000 of fake money and tries to compound it rapidly by
researching public information, forming falsifiable hypotheses, and managing a
multi-position long/short book across stocks and native crypto. Prediction
markets are allowed when the evidence supports a real pricing edge.

This is an aggressive engineering experiment, not a return promise. The system
may take concentrated and high-variance paper risk inside its checked-in
mandate, but it must never place, cancel, or otherwise mutate a real order,
account, transfer, or wallet.

## Product direction

- Run without a routine human approval step. The agent chooses what to research,
  what to hold, direction, sizing, entries, exits, and when a thesis is broken.
- Search broadly across the public internet and direct public market-data
  sources. Compare opportunities instead of anchoring on a fixed watchlist.
- Manage a portfolio, not a single bet. Prefer several genuinely independent,
  high-conviction positions when they exist; do not diversify into weak ideas or
  churn tiny positions merely to look active.
- Be aggressive on opportunity selection and fast on thesis invalidation. High
  risk is acceptable only when the expected payoff, evidence, liquidity, costs,
  and explicit downside make the bet attractive.
- Treat cash, longs, shorts, and rapid reversals as valid active decisions. A
  hold is valid when no researched edge survives costs, but the agent must first
  search a broad opportunity set.
- Learn from the immutable record. Every cycle must revisit open hypotheses,
  inspect prior outcomes and losing exits, state what changed, and record which
  lessons influenced the new portfolio.
- Optimize for long-run compounded NAV and risk-adjusted decision quality, not
  trade count, excitement, or a fabricated claim of market-beating skill.

## The brain

The brain is an auditable decision journal, not hidden chain-of-thought. Store
concise decision-relevant reasoning:

- market regime and opportunity set considered;
- portfolio intent and important changes since the prior cycle;
- one structured hypothesis per open or ordered instrument;
- mechanism, catalysts, falsifiers, expected horizon, confidence, target, and
  invalidation price;
- alternatives rejected, material risks, and lessons applied from prior cycles.

The next cycle must receive a compact, deterministic memory built from the
append-only ledger: recent decisions, subsequent NAV direction, fees, losing and
winning realized exits, current unrealized P&L, and the latest hypothesis for
each open position. Do not claim that next-cycle NAV movement proves causal
trade attribution.

## Authority and safety boundary

- Scheduled operation is paper-only. Never add a live mandate, broker adapter,
  credential, execution permit, or mutating financial tool to the scheduled
  path.
- Robinhood or other account access, if present, is read-only context and is not
  required for the paper fund.
- Models propose. Typed accounting and policy code authorizes. The agent cannot
  bypass cash, inventory, concentration, gross/net/short exposure, turnover,
  drawdown, freshness, evidence, or idempotency checks.
- Capitalize the fund once with exactly $1,000. Never add daily contributions,
  reset losses, rewrite history, or change an initialized mandate in place.
- Keep the exact one-packet/one-apply scheduled sequence. A failed cycle key is
  terminal: stop, preserve the evidence, and never mutate or retry it to pass a
  gate.
- All fills are simulated. Never describe them as broker or live fills.
- Options remain out of scope until the domain has explicit contracts for
  multipliers, expiry, exercise/assignment, spreads, liquidity, and worst-case
  loss. Do not disguise options exposure as stock or crypto.

## Data and audit principles

- Use current public sources and direct APIs/pages where practical. Retain the
  source URL, source timestamp, observation timestamp, claim, relevant
  instruments, and enough content to audit the decision.
- Set the final decision cutoff after research. No evidence or quote may be
  newer than `decision.as_of`.
- Save every accepted decision, journal, hypothesis, quote, evidence item, risk
  check, simulated fill, fee, state transition, runtime version, and error in
  the append-only hash-chained ledger.
- Never log credentials, OAuth tokens, account numbers, private account data,
  personal data, or unnecessary copied web content.
- Prefer independent sources for important claims. A price move, social post, or
  prediction-market price is an input, not by itself an investment thesis.

## Engineering standards

- Keep the active design explainable in one sentence: Codex proposes a sourced
  portfolio decision; deterministic code applies it to a persistent fake-money
  ledger.
- Favor cohesive typed Python, explicit interfaces, Decimal money math, UTC
  timestamps, small functions, boring storage, and clear failure modes.
- Keep one active scheduled fund workflow. Do not create a parallel orchestrator
  or duplicate accounting engine.
- Preserve backward replay of immutable historical cycles when evolving schemas.
- Make all runs and orders idempotent. Persist intent before any state change and
  verify the full accounting replay and event chain after every cycle.
- Add unit tests for financial math and policy, integration tests for boundaries,
  and end-to-end tests for the paper workflow. Cover many simultaneous positions,
  long/short transitions, stale data, costs, insufficient cash, drawdown,
  duplicates, failures, and restarts.
- Keep dependencies few and dependable. Add a framework only when it removes
  meaningful complexity.
- Keep the CLI as the primary operational interface and documentation/examples
  executable.

## Change workflow

1. Inspect the active paper-fund path and preserve working accounting, audit,
   research, and backtesting behavior.
2. Implement vertical milestones that leave the repository runnable.
3. Validate focused behavior after each milestone, then run the full test, lint,
   operational smoke, accounting replay, and security suites.
4. Use real public read-only market data for final integration evidence when it
   is available. Never fabricate a successful source or broker check.
5. Keep changes small, coherent, reviewable, and free of unrelated cleanup.
