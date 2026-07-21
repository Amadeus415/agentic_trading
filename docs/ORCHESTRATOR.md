# Edgecraft orchestrator contract

This is the operating contract for an agent that can use both the `edgecraft` CLI and Robinhood's authenticated Trading MCP.

## Non-negotiable boundary

Edgecraft never stores Robinhood credentials. `CodexRuntime` launches a structured Codex turn that uses the host's authenticated Robinhood MCP session; Python never receives OAuth tokens. Edgecraft owns mandates, budgets, research, deterministic limits, proposal identity, single-use permits, reconciliation, and the audit trail. See [AUTONOMY.md](AUTONOMY.md) for the primary unattended workflow; this document also describes the lower-level manual protocol.

An approved Edgecraft proposal means **approved for Robinhood review**. It is not an order. A live order may be placed only after:

1. Fresh account, portfolio, position, quote, tradability, and open-order reads.
2. A freshly recomputed Edgecraft live proposal with no violations.
3. A successful `review_equity_order` response for the exact order.
4. The active mandate is explicitly live and its checked-in policy has `trading_enabled=true`.
5. Edgecraft has issued one unexpired permit for the exact proposal/order key.
6. The Codex `PreToolUse` hook claims that permit before allowing `place_equity_order`.
7. The proposal/order key has not previously been placed.

If any input changes after review, discard the review and start again.

## Agent workflow

### 1. Prove the environment is ready

```bash
edgecraft health --real-data-symbol SPY
edgecraft context \
  --config examples/context.browserbase.json \
  --symbols VTI,VXUS,BND \
  --output artifacts/current-context.json
edgecraft protocol
```

`health` proves that the official MCP endpoint is enabled, real OHLCV can be
downloaded, and the Browserbase credential is configured. `context` performs a
real, read-only current-web collection. Neither proves that a particular account
can trade. Always call `get_accounts`; select only the dedicated account returned
with `agentic_allowed=true`.

### 2. Research a fixed hypothesis

Write the hypothesis, universe, dates, parameters, benchmark, costs, and pass/fail rule before running it.

```bash
edgecraft backtest \
  --config examples/research.json \
  --data-source market \
  --output artifacts/research.json

edgecraft walk-forward \
  --config examples/research.json \
  --data-source market \
  --train-sessions 504 \
  --test-sessions 126 \
  --output artifacts/walk-forward.json
```

Repeat the backtest with materially higher costs, then derive rather than hand-author the evidence:

```bash
edgecraft backtest \
  --config examples/research.json \
  --data-source market \
  --cost-multiplier 5 \
  --output artifacts/cost-stress.json

edgecraft evidence \
  --backtest artifacts/research.json \
  --walk-forward artifacts/walk-forward.json \
  --cost-stress artifacts/cost-stress.json \
  --strategy value_tilted_dca \
  --output artifacts/research-evidence.json
```

A strategy can be promoted only if it beats the appropriate baseline, is the consistently selected walk-forward candidate, passes cost stress, and passes the configured PBO/Deflated-Sharpe multiple-testing thresholds. The evidence artifact is content-addressed.

### 3. Refresh Robinhood state

Use the MCP tools in this order:

1. `get_accounts`
2. `get_portfolio`
3. `get_equity_positions`
4. `get_equity_orders`
5. `get_equity_quotes` for every held or target symbol
6. `get_equity_tradability` for every proposed symbol

Transform the results into the canonical contracts shown in `examples/snapshot.example.json` and `examples/quotes.example.json`. Preserve the exact account id only in a local ignored artifact; never commit it. `portfolio_value`, `buying_power`, prices, quantities, timestamps, and eligibility must come from the same refresh cycle.

### 4. Analyze before proposing

```bash
edgecraft portfolio --snapshot artifacts/snapshot.json
```

Investigate unaccounted value, concentration, stale data, an unexpected position, an open order, an account restriction, or a mismatch before continuing.

### 5. Shadow first

```bash
edgecraft propose \
  --snapshot artifacts/snapshot.json \
  --quotes artifacts/quotes.json \
  --targets examples/targets.json \
  --policy examples/policy.shadow.json \
  --strategy value_tilted_dca \
  --mode shadow \
  --research artifacts/research-evidence.json \
  --output artifacts/proposal.json
```

Shadow mode may produce review instructions, but it must never call `place_equity_order`. Run multiple scheduled shadow cycles and compare proposed versus subsequently observable execution prices and portfolio outcomes.

### 6. Explicitly promote the policy

Live mode requires a separate policy file with `trading_enabled: true`. Do not toggle it because a strategy “looks good.” Promotion requires a governing user instruction, passing evidence, a settled loss/monitoring budget, and successful shadow operation.

The supplied policy is intentionally shadow-only and bounded for approximately $500:

- Explicit symbol whitelist
- $50 maximum per order
- $100 maximum placed notional per UTC day
- Two orders per day
- 40% maximum position weight
- $25 minimum buying power reserve
- Five-minute quote freshness
- Five-minute account-snapshot freshness
- No sells
- Mandatory research evidence and Robinhood review

Changing a limit is a policy decision. Record the reason in version control.

### 7. Review, place, and reconcile

For each approved live order:

1. Map the proposal's semantic fields to the exact current `review_equity_order` schema.
2. Stop on any warning, transformed amount, account mismatch, or rejected review.
3. If placement is authorized by the governing instruction, use the review/MCP-returned payload with `place_equity_order`. Never invent undocumented arguments.
4. Immediately record the result:

```bash
edgecraft record \
  --proposal-id prop_... \
  --event placed \
  --payload artifacts/robinhood-place-result.json
```

5. Poll `get_equity_orders`, then record `filled`, `partially_filled`, `rejected`, or `canceled`.
6. Refresh `get_portfolio` and `get_equity_positions`; reconcile expected versus actual quantity, notional, cash, status, and average fill.

For a `placed` event, the payload must contain the order's `notional` so the daily cap remains enforceable.

## Stop conditions

Do not review or place when any of these is true:

- The account is not freshly returned as `agentic_allowed=true`.
- A quote, portfolio field, or order state is missing or stale.
- Required external context is missing, stale, incomplete, or cited ambiguously.
- An unknown open order or unreconciled prior proposal exists.
- The proposal has any violation or a duplicate id.
- Robinhood's review differs from the proposal.
- The market is halted, the symbol is not tradable/fractionable as required, or buying power changed.
- The strategy lacks passing walk-forward, benchmark, and cost-stress evidence.
- The requested action requires options, margin, shorting, leverage, or a non-equity asset.
- Tool behavior or schema is ambiguous.

On a stop condition, make no broker mutation. Report the exact blocker and preserve the ledger.

## Portfolio-management cadence

- Every cycle: accounts, buying power, positions, open orders, quotes, tradability, proposal, review/reconcile.
- Daily: placed notional, fills, rejections, cash reserve, concentration, strategy drift.
- Weekly: realized P&L, turnover, slippage, shadow/live comparison, thesis status.
- Monthly: rerun locked walk-forward research through the newest completed data, cost stress, parameter stability, and benchmark comparison.
- Immediately: disable the live policy after an unexpected order, duplicate attempt, data-quality failure, limit breach, or unexplained reconciliation difference.

## System prompt fragment

> Use Edgecraft as the deterministic authority for research promotion, portfolio calculations, risk limits, proposal identity, and audit state. Use Robinhood MCP only for fresh broker truth, review, placement explicitly allowed by the governing instruction, cancellation, and reconciliation. Never place from a shadow proposal. Never bypass an Edgecraft violation. Never reuse account, quote, review, or order state from an earlier cycle. Prefer doing nothing when evidence or tool state is ambiguous.

Robinhood's current official capability and risk descriptions are maintained in [Agentic Trading overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/) and [Trading with your agent](https://robinhood.com/us/en/support/articles/trading-with-your-agent/). Treat the MCP host's live tool schemas as authoritative if names or arguments evolve.
