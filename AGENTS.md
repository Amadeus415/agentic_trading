# Edgecraft Agent Instructions -

## Mission
### Build a Fully Agentic Paper-Trading Fund
Build an understandable, production-quality agentic paper-trading fund. The
system observes read-only account and market context, researches current market
conditions, forms and tests a daily hypothesis, and records simulated trades in
an auditable paper portfolio. Scheduled operation must never place, cancel, or
otherwise mutate a real Robinhood order.

This is a backend-first project. Prefer durable domain modules, a strong CLI,
machine-callable tools, and explicit data contracts over frontend work.

# Goals From the Human

I want this to be a high-performing agentic paper fund, built on Codex and run
daily through a scheduled task with no routine human step. All trades are fake;
Robinhood access is read-only context. Keep code understandable and avoid
unneeded complexity.

## Product principles

- Autonomy means no routine human approval step for research, decisions, and
  simulated paper-portfolio updates.
- Autonomy does not mean unbounded authority. Every action must pass
  deterministic, code-enforced mandate, cash, concentration, liquidity,
  drawdown, turnover, market-hours, and data-freshness checks that the reasoning
  agent cannot bypass. Keep these pretty light and don't overdo them
- Keep scheduled mandates and development workflows in shadow/paper mode. Never
  add a live mandate to the scheduled entrypoint.
- Capitalize the simulated fund with exactly $1,000 once. Never inject a daily
  contribution or silently reset losses. A hold is valid when evidence is weak.
- The paper fund may propose buys, sells, shorts, and covers across public
  stocks, native crypto, and prediction markets without routine approval. Its
  freedom is bounded by deterministic accounting, exposure, turnover,
  concentration, drawdown, freshness, and evidence checks.
- Separate probabilistic reasoning from deterministic controls. Models may
  propose; typed policy and risk engines authorize.
- Optimize for repeatable decision quality, costs, taxes, diversification, and
  risk-adjusted long-horizon outcomes—not activity or short-term prediction.

## Data principles
- Let's consume all needed data to have a cutting edge agentic hedge fund
- The orchestrator agent should have the full amount of tools to fully reason through any and all financial data, internet data, and anything else to find the best position to open.
- Every single piece of data in the workflow should be saved and auditable

## Engineering standards

- Keep modules cohesive and boring: typed Python, explicit interfaces, small
  functions, dependency injection at broker/data/model boundaries, and clear
  failure modes.
- Use decimal arithmetic for money and quantities. Store all timestamps in UTC
  and retain source timestamps for external data.
- Make every run and order idempotent. Persist intents before side effects and
  reconcile broker state after every submission, timeout, restart, or retry.
- Maintain an append-only decision and execution audit trail containing inputs,
  source freshness, hypothesis, alternatives, policy/risk results, model and
  prompt versions, orders, fills, fees, errors, and reconciliation results.
- Never log credentials, OAuth tokens, account numbers, or unnecessary personal
  data. Keep secrets outside the repository.
- Broker and model integrations must have fakes for deterministic tests. Real
  account validation is read-only unless live execution was separately armed by
  the account owner.
- Favor a small, dependable dependency set. Add a framework only when it removes
  meaningful complexity or improves reliability.
- Add unit tests for financial math and policy rules, integration tests for
  boundaries, and end-to-end tests for dry-run/paper workflows. Test retries,
  duplicate runs, partial fills, stale data, market closure, insufficient cash,
  and process restarts.
- Observability must include structured logs, metrics, traces, health/readiness
  checks, run status, broker reconciliation, and actionable failure reasons.
- Keep documentation and examples executable. The primary operational path must
  be available through the CLI without editing source.

## Change workflow

1. Inspect existing architecture and preserve working research/backtesting
   behavior.
2. Implement vertical milestones that leave the repository runnable.
3. Validate proportionally after each milestone and run the full suite before
   declaring completion.
4. Use real, read-only market and account data for final integration evidence
   when credentials and services are available; never fabricate a successful
   live broker check.
5. Commit in small, coherent, reviewable units. Do not mix unrelated cleanup
   into feature commits.
