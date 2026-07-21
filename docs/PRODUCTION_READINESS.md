# Production readiness for autonomous trading

Edgecraft is designed as a bounded autonomous portfolio manager, not as a
promise of hedge-fund returns. The production objective is repeatable,
observable decision quality with small and reversible capital exposure. Models
research and propose; ordinary code owns authority.

## External benchmark

The current agentic-finance ecosystem is useful in two different ways:

- [TradingAgents](https://github.com/TauricResearch/TradingAgents) demonstrates
  specialist analyst roles, opposing bull/bear arguments, risk debate, and a
  portfolio-manager synthesis.
- [Microsoft RD-Agent](https://github.com/microsoft/RD-Agent) and
  [Qlib](https://github.com/microsoft/qlib) demonstrate an automated research
  loop that proposes factors/models, implements them, evaluates them, and feeds
  results into the next iteration.
- [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) separates
  perception, reasoning, action, LLM operations, and data operations.

Those projects inform Edgecraft's research and evaluation loop. They are not a
reason to let a committee of language models directly control a broker. In this
repository, model diversity and debate belong before the deterministic policy
boundary. A typed proposal, not persuasive prose or agent consensus, is the only
input to execution controls.

The control plane follows the principles in the
[SEC Market Access Rule overview](https://www.sec.gov/rules-regulations/2011/06/risk-management-controls-brokers-or-dealers-market-access)
and [FINRA algorithmic-trading guidance](https://www.finra.org/rules-guidance/key-topics/algorithmic-trading):
pre-set capital/error controls, controlled access, pre-production testing,
immediate post-trade reporting, ongoing surveillance, and documented review.
Edgecraft is not claiming that these rules directly make a personal account a
regulated broker-dealer; they are used as strong engineering benchmarks.

Agent security follows the
[OWASP AI Agent Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html)
and the [NIST AI RMF](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/):
least privilege, untrusted-context isolation, tool allowlisting, traceability,
continuous evaluation, incident response, safe failure, and recovery.

## Live execution state machine

    due + idempotency lock
      -> completed-session full-universe market intelligence
      -> fresh web, regulatory, and social context
      -> read-only broker observation
      -> typed recommendation
      -> deterministic portfolio risk gate
      -> read-only broker preflight and review
      -> deterministic preflight risk gate
      -> policy fingerprint re-check
      -> one expiring single-use permit
      -> exact broker placement
      -> terminal reconciliation
      -> append-only audit, SPY comparison, and metrics

The preflight occurs before authority exists. It refreshes account eligibility,
positions, open orders, quote, tradability, market session, bid/ask spread, and
20-session average daily dollar volume. The policy is fingerprinted at proposal
time and re-read before and after preflight; any change aborts execution.

## Deterministic live controls

Every live policy must explicitly define:

- account eligibility and restriction status;
- symbol and group whitelists;
- managed capital, per-order, daily-notional, and daily-order caps;
- cash reserve and position/group concentration;
- quote and account-snapshot freshness;
- regular/extended market sessions allowed;
- maximum bid/ask spread;
- maximum order fraction of average daily dollar volume;
- maximum rolling seven-day turnover;
- maximum portfolio drawdown from audited observations;
- minimum successful shadow history;
- research evidence requirements;
- broker review or an explicitly recorded standing authorization;
- exact-order permits, reconciliation, and the kill switch.

The readiness command with the require-ready flag checks the static and
persisted control plane before a scheduled run. The cycle command repeats the
dynamic controls with fresh broker data. Passing readiness is necessary, not
sufficient, for a trade.

## Promotion standard

For an active strategy, promotion should require:

1. A frozen hypothesis, universe, benchmark, costs, and pass/fail rule.
2. Causal execution assumptions and point-in-time data.
3. Walk-forward selection on untouched windows.
4. Deflated Sharpe and backtest-overfitting checks.
5. Material spread, slippage, and commission stress.
6. Parameter and regime stability.
7. At least the policy's required successful shadow cycles.
8. Tiny initial capital and order limits.
9. Explicit account-owner arming of one mandate and one account.
10. Continuous post-trade slippage, drift, failure, and reconciliation review.

No backtest, agent debate, or readiness check establishes future profitability.
The default response to missing, stale, contradictory, or ambiguous evidence is
to hold cash.
