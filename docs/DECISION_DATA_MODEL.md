# Decision data model

Each cycle input has exactly two top-level members: `decision` and `quotes`. Run `make fund-context` for the current machine-readable JSON Schema.

## Decision

`FundDecision` records:

- stable decision, fund, and cycle identities;
- UTC decision time;
- `trade` or `hold`;
- thesis, alternatives, and risks;
- embedded evidence inventory;
- zero or more explicit-side orders.

A trade requires orders. A hold forbids orders. Every order cites known evidence. Evidence scoped to instrument IDs cannot support a different instrument.

## Evidence

`FundEvidence` retains a source name, direct URL, observed time, claim, summary, relevant instruments, and optional source content. Secrets and private account data are prohibited.

## Quotes

`FundQuote` retains a quote ID, instrument ID, asset class, Decimal price, UTC source/observation time, source name/URL, and `open` or `settled` status. Every open position and order needs a fresh quote.

## Orders

`FundOrder` records instrument, asset class, side, positive fractional quantity, rationale, and evidence IDs. Sides have exact meanings: `buy`, `sell`, `short`, and `cover` are not interchangeable.

## Persistence

The normalized objects are stored verbatim in an immutable cycle row. Their canonical SHA-256 digest is included in the event chain and recomputed during verification.
