# History

Edgecraft changes over time. This folder holds the record of how it changed and what each version did.

| Era | Fund ID | Dates | Result | Record |
| --- | --- | --- | --- | --- |
| v1: multi-asset | `edgecraft-aggressive` | 2026-08-22 → 2026-10-05 | $1,000 → $1,020.41, 22 closed trades | [v1-multi-asset](v1-multi-asset/README.md) |
| v2: prediction markets | `edgecraft-predictions` | from 2026-10-15 | fresh $1,000, new track record | live ledger |

Each era is a separate fund in the same append-only ledger. A new era never inherits the previous era's track record, and old cycles are never rewritten.

## Linking code to performance

- [`CHANGELOG.md`](../CHANGELOG.md) records why each trading change was made and what it should move.
- `make fund-lineage` groups a fund's cycles by the code revision that applied them, with NAV change, fills, and fees for each revision.
  - **v2:** every cycle records its revision directly.
  - **v1:** cycles predate that field. Their revision is inferred from [`deployments.json`](deployments.json), built from the runtime checkout's git reflog and, before the runtime existed, from commit dates.

Lineage shows which code was live during each stretch. It does not prove that a change caused a result: positions opened under one revision can be marked under the next, and most segments hold only a handful of trades.
