# Changelog: what changed, why, and what it should move

This file is append-only. Add new entries at the bottom and never edit or delete old ones. If an entry turned out wrong, write a later entry that says so.

Each trading-relevant change records four things:

- **Why**: the problem it addresses, with evidence.
- **Expected effect**: which metric should move, and in which direction.
- **Measure**: how `make fund-lineage` or `make fund-report` would show it.
- **Fund**: the ledger fund that runs the change.

Every v2 cycle stores the git commit that applied it (`source_revision`). Run `make fund-lineage` to see performance per revision next to these entries. For v1 cycles, the revision is inferred from deploy times in [`history/deployments.json`](history/deployments.json).

---

## Era v1: multi-asset (2026-07-13 → 2026-10-05) · fund `edgecraft-aggressive`

The full record is in [history/v1-multi-asset](history/v1-multi-asset/README.md) and the code is tagged `v1-multi-asset`. A single Codex researcher traded stocks, crypto, and Polymarket contracts with a 72-hour horizon.

- **Result:** NAV $1,000 → $1,020.41 over 96 cycles and 22 closed trades. The expectancy interval spans zero.
- **Lesson:** stocks lost $41.28 in realized fills, and their scored ideas had a profit factor of 0.26. Prediction contracts driven by news and resolution reading made money. BTC-threshold contracts were crypto price bets in disguise and produced the largest loss.
- **Lesson:** no cycle recorded its code revision, so v1 changes can only be attributed by inference.

---

## 2026-10-15 · Record the code revision on every cycle
- **Why:** v1 recorded `edgecraft_version: "1.0.0"` on all 96 cycles, so no performance change could be traced to a code change.
- **Expected effect:** none on trading. Every new cycle carries `source_revision` (the exact checked-out commit, with `+dirty` for uncommitted or untracked files).
- **Measure:** `make fund-lineage` shows `basis: recorded` for every v2 segment.
- **Fund:** all.
