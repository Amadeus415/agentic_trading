# Decision data model

Each cycle input has two required top-level members, `decision` and `quotes`, plus optional runtime provenance. Run `make fund-context` for the current machine-readable JSON Schema.

## Decision

`FundDecision` records:

- stable decision, fund, and cycle identities;
- UTC decision time;
- `trade` or `hold`;
- thesis, alternatives, and risks;
- an auditable decision journal;
- embedded evidence inventory;
- zero or more explicit-side orders.

A trade requires orders. A hold forbids orders. Every order cites known evidence. Evidence scoped to instrument IDs cannot support a different instrument.

## Decision journal

Scheduled cycles require `journal` with the observed market regime, opportunity
set considered, portfolio intent, what changed, and lessons applied. Its
`hypotheses` list records one current entry for every open or ordered instrument:
stance, statement, mechanism, catalysts, falsifiers, horizon, confidence,
optional target/invalidation prices, and evidence IDs. This is concise,
decision-relevant rationale—not private chain-of-thought.

Historical v1 cycles without journals remain replayable. An absent optional
journal is omitted from their canonical digest; once a journal is present it is
part of the immutable request digest.

## Evidence

`FundEvidence` retains a source name, direct URL, observed time, claim, summary, relevant instruments, and optional source content. Secrets and private account data are prohibited.

## Quotes

`FundQuote` retains a quote ID, instrument ID, asset class, Decimal price, UTC source/observation time, source name/URL, and `open` or `settled` status. Every open position and order needs a fresh quote.

## Orders

`FundOrder` records instrument, asset class, side, positive fractional quantity, rationale, and evidence IDs. Sides have exact meanings: `buy`, `sell`, `short`, and `cover` are not interchangeable.

## Persistence

The normalized objects are stored verbatim in an immutable cycle row. Their canonical SHA-256 digest is included in the event chain and recomputed during verification.
