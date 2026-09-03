# Paper-fund accounting contract

The paper fund is a deterministic state machine around one $1,000 bankroll. Codex supplies research, a typed decision, and sourced marks. It cannot supply cash or mutate stored state directly. For how the session, monitor, and evolution loops sit around this contract, see [DESIGN.md](DESIGN.md).

Run `make fund-context` for the current machine-readable JSON Schema. The executable static fixture is [fund-cycle.starting.example.json](../examples/fund-cycle.starting.example.json).

## Growth objective

The human-facing README still names $100,000 over ten years as the long-run
dream. That figure is deliberately absent from `fund-context` and the
operating prompt so it cannot distort trade selection. `fund-show --history`
can still report progress for humans. The objective has no authority to bypass
accounting, evidence, freshness, drawdown, concentration, or cash checks.

Dollar exposure and turnover limits remain the bootstrap floors. When
`scale_limits_with_nav` is enabled, their effective ceilings grow only with
earned NAV using checked-in NAV multiples. Deposits cannot enlarge them because
capitalization remains a one-time immutable $1,000 event. Each effective limit
is written into the cycle's risk audit record.

## State

For signed position quantity `q` and current mark `p`:

```text
position market value = q × p
NAV                   = cash + Σ(position market value)
gross exposure        = Σ(abs(position market value))
net exposure          = Σ(position market value)
short exposure        = current short market value, except binary shorts use
                        their remaining worst-case settlement liability
drawdown              = (peak NAV - current NAV) / peak NAV
```

Positive quantity is long; negative quantity is short. Every money, price, fee, and quantity calculation uses `Decimal`.

## Simulated fills

When a quote includes displayed bids/asks, the fill walks that book. Otherwise
execution prices include adverse slippage. A monitor stop that was gapped
through adds extra adverse slippage. Fees apply symmetrically. Stock borrow
accrues on cover when the position recorded an annual borrow fee. Historical
packets without book or borrow fields replay with the original last-plus-slippage
model.

| Side | Inventory rule | Cash change | Realized P&L when closing |
|:--|:--|:--|:--|
| `buy` | Cannot cover a short | `-(gross + fee)` | None |
| `sell` | Cannot exceed a long | `gross - fee` | `(execution - average entry) × quantity - fee` |
| `short` | Cannot reduce a long | `gross - fee` | None |
| `cover` | Cannot exceed a short | `-(gross + fee)` | `(average entry - execution) × quantity - fee` |

Prediction instruments use prices between `0` and `1`. An open contract cannot be marked exactly `0` or `1`. A sourced `settled` quote must be exactly `0` or `1`; settlement closes the position once with no invented fee or slippage.

A binary short reserves enough cash to pay `$1 × short quantity` if every contract resolves against the fund. The short proceeds cannot be redeployed below that reserve. Reported prediction short exposure uses the remaining worst-case loss `(1 - mark) × quantity`, not the usually smaller current marked liability.

## Decision packet

Each cycle input has two required top-level members, `decision` and `quotes`, plus optional runtime provenance.

```json
{
  "decision": {
    "decision_id": "...",
    "fund_id": "edgecraft-aggressive",
    "cycle_key": "...",
    "as_of": "UTC timestamp",
    "action": "trade or hold",
    "thesis": "...",
    "alternatives": "...",
    "risks": "...",
    "journal": {
      "market_regime": "...",
      "opportunity_set": "...",
      "portfolio_intent": "...",
      "what_changed": "...",
      "lessons_applied": [],
      "hypotheses": []
    },
    "evidence": [],
    "orders": []
  },
  "quotes": []
}
```

`FundDecision` records stable identities, UTC decision time, `trade` or `hold`, thesis/alternatives/risks, an auditable journal, embedded evidence, and zero or more explicit-side orders. A trade requires orders. A hold forbids orders. The sizing pass may turn a proposed trade into a hold when every entry is below the edge threshold.

Scheduled cycles require `journal` with the observed market regime, opportunity set considered, portfolio intent, what changed, and lessons applied. Its `hypotheses` list records one current entry for every open or ordered instrument: stance, mechanism, catalysts, falsifiers, horizon, `p_win`, target/invalidation, playbook, driver, and evidence IDs. Scheduled hypotheses may not exceed 72 hours. Cash is allowed only after researched candidates are measured against costs. Historical packets with `confidence` remain replayable. This is concise decision rationale, not private chain-of-thought.

Historical v1 cycles without journals remain replayable. An absent optional journal is omitted from their canonical digest; once a journal is present it is part of the immutable request digest.

`FundEvidence` retains a source name, direct URL, observed time, claim, summary, relevant instruments, and optional source content. Secrets and private account data are prohibited. Every order cites known evidence. Evidence scoped to instrument IDs cannot support a different instrument.

`FundQuote` retains a quote ID, instrument ID, asset class, Decimal price, UTC source/observation time, source name/URL, and `open` or `settled` status. Every open position and order needs a fresh quote.

`FundOrder` records instrument, asset class, side, belief fields, rationale, and evidence IDs. Entry quantity may be null and is ignored by belief sizing; exit inventory stays explicit. Sides have exact meanings: `buy`, `sell`, `short`, and `cover` are not interchangeable.

The normalized objects are stored verbatim in an immutable cycle row. Their canonical SHA-256 digest is included in the event chain and recomputed during verification.

## Atomicity and provenance

- A fresh fund has one immutable capitalization event and no positions.
- Every cycle stores the normalized decision, embedded evidence, quotes, simulated fills, resulting state, and a SHA-256 digest.
- Scheduled cycles require a structured journal and a refreshed hypothesis for every open or ordered instrument.
- Scheduled cycles reject hypotheses beyond 72 hours. They allow cash only after the sizing audit records why proposed entries missed the after-cost edge threshold.
- Every completed cycle also stores a structured audit sidecar: risk-check outcomes (observed value vs limit), quote freshness, fee totals, mandate digest, Edgecraft version, optional model/prompt metadata, input file SHA-256, sleeve weights, and the sizing audit.
- Hash-chained `cycle_completed` events retain the full decision, quotes, fills, settlements, state, and audit sidecar—not only a summary—so the event stream alone is a complete audit trail.
- `(fund_id, cycle_key)` is unique. An identical replay returns the prior result; a different payload under that key is rejected.
- Cycles apply in one SQLite transaction. Validation failure persists no cycle and changes no balance.
- Rejected normalized decisions are retained as `cycle_rejected` audit events with their exact packet digest, reason, decision, quotes, runtime provenance, and structured risk evaluation when a policy limit failed.
- Events form a SHA-256 chain. SQLite triggers prohibit update/delete on fund, cycle, and event records.
- `fund-verify` recomputes request digests, replays every cycle from the original $1,000, compares positions/cash/NAV, and verifies the event chain.
- `fund-cycle --cycle-key` retrieves the immutable packet. Add `--audit` for related events and sidecar completeness gaps. Run `fund-verify` for hash-chain and accounting replay.
- Later cycles cannot carry an `as_of` earlier than the prior completed cycle.

The domain is paper-only by construction: it defines no live mode and imports no broker adapter.
