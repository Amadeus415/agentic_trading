# Edgecraft Agent Instructions

## Mission

Build an understandable, production-quality agentic portfolio manager for the
stock market. The system accepts a portfolio mandate such as “invest $10 every
week into index funds at attractive prices,” observes the account and its trade
history, researches current market conditions, forms and tests a weekly
hypothesis, and can autonomously place and monitor trades through Robinhood.

This is a backend-first project. Prefer durable domain modules, a strong CLI,
machine-callable tools, and explicit data contracts over frontend work.

## Product principles

- Autonomy means no routine human approval step. Once a mandate is explicitly
  armed for live execution, the agent may research, decide, execute, reconcile,
  and recover without human intervention.
- Autonomy does not mean unbounded authority. Every action must pass
  deterministic, code-enforced mandate, cash, concentration, liquidity,
  drawdown, turnover, market-hours, and data-freshness checks that the reasoning
  agent cannot bypass.
- Default new mandates and development workflows to paper or dry-run execution.
  Enabling live trading must be explicit, scoped to one account and mandate,
  recorded in the audit log, and reversible with a kill switch.
- Treat the weekly contribution as a hard spending ceiling, not a target that
  justifies poor trades. Cash carryover is allowed when policy permits it.
- Separate probabilistic reasoning from deterministic controls. Models may
  propose; typed policy and risk engines authorize.
- Optimize for repeatable decision quality, costs, taxes, diversification, and
  risk-adjusted long-horizon outcomes—not activity or short-term prediction.
- Never promise returns. Make uncertainty, stale or missing data, estimated
  costs, rejected decisions, and degraded operation visible.

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
