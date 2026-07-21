# Decision data model

Every autonomous attempt that reaches a valid model decision writes one
immutable `edgecraft.decision-audit.v1` packet before Edgecraft creates a trade
proposal or issues execution authority. The packet is stored in SQLite's
`decision_packets` table and addressed by a SHA-256 digest of its canonical JSON.

```text
mandate + risk policy + promotion research + external context
                              │
                              ▼
                 read-only broker observation
                              │
                              ▼
                    decision audit packet
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
          deterministic proposal     invest / hold reasoning
                 │
                 ▼
       preflight → permit → order → reconciliation
```

## The decision packet

| Field | What it preserves |
| --- | --- |
| `run_id`, `attempt`, `recorded_at` | Cycle identity, retry identity, and UTC completion time. |
| `runtime` | Prompt contract version, configured model, and reasoning effort. |
| `mandate` | The owner goal, mode, budget, universe, weights, schedule, and configured data paths used for this attempt. |
| `risk_policy` | The complete deterministic limits snapshot—not only a policy filename that can later change. |
| `research_evidence` | The promotion experiment and pass/fail gates used by policy, when configured. |
| `external_context` | The exact normalized packet shown to the model: Browserbase queries and results, fetched excerpts, URLs, titles, authors, publication/retrieval times, SEC filing metadata, social posts, warnings, and completeness/freshness counts. |
| `market_intelligence` | The content-hashed completed-session universe comparison shown to the model, including trend, volatility, downside risk, drawdown, liquidity, beta, breadth, and regime. |
| `observation.account` | Fresh buying power, portfolio value, positions, open orders, restriction state, broker source, and source time. The real account ID is replaced with a stable one-way reference before storage. |
| `observation.quotes` | Symbol, last/bid/ask, tradability, market session, average daily dollar volume, and source time. |
| `observation.recent_order_summary` | Recent broker order context returned by the observation agent. |
| `observation.realized_pnl_summary` | Realized and trade-by-trade P&L context returned by the observation agent. |
| `observation.decision` | The model's structured invest/hold judgment and its evidence inventory. |

The packet is append-only. A side-effect-free retry gets a new attempt number
and a new packet; an earlier attempt is never overwritten.

## Model reasoning and evidence

Edgecraft stores a structured explanation, not private chain-of-thought. The
decision contains:

- action, confidence, hypothesis, risks, and alternatives considered;
- prose evidence and named data sources;
- every cited Browserbase/SEC/social `context_source_id`;
- a typed `evidence_items` inventory for every material broker fact, quote,
  fundamental, technical indicator, historical statistic, research result, or
  external fact used by the model;
- per-allocation rationale and the exact evidence IDs supporting that symbol.

Each evidence item records category, source, optional symbol, observation time,
source time, summary, named values with units, and related context source IDs.
Any decision with no evidence inventory, or an invest allocation with no
evidence IDs, is rejected before proposal creation.

## Related append-only records

The decision packet is the replayable input/output record. The other tables
capture state transitions:

| Table | Role |
| --- | --- |
| `mandates` | Latest registered owner configuration for scheduling and lookup. The immutable per-run copy lives in `decision_packets`. |
| `runs` | One idempotent state machine per mandate cycle. |
| `runtime_events` | Timeline summaries such as context collection, observation completion, risk results, permits, recovery, and reconciliation. |
| `proposals` | Full typed orders, policy digest, research evidence, deterministic risk result, and a copy of the structured model reasoning. |
| `permits` | Expiring, single-use execution authority and redacted exact-order constraints. |
| `events` | Broker review, placement, fill, rejection, and cancellation transitions with the proposal reasoning attached. |

## Inspecting one decision

```bash
edgecraft runs --ledger state/edgecraft.db
edgecraft decision \
  --ledger state/edgecraft.db \
  --run-id RUN_ID
```

Recompute SHA-256 over the packet's canonical JSON (sorted keys and compact
separators) to verify `payload_sha256`.

## Deliberate storage boundary

Edgecraft saves all normalized data exposed to or returned by the decision
contract. It does not save credentials, OAuth tokens, real account IDs, hidden
model chain-of-thought, or entire raw web pages and opaque MCP response bodies.
Browserbase content is sanitized into bounded excerpts before the model sees it;
that exact normalized content is what the audit packet preserves. This keeps the
record replayable without turning the ledger into a secrets store or an
unbounded copy of third-party content.
