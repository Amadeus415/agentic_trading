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


## 2026-10-17 · Start a separate prediction-market experiment
- **Why:** archived v1 stock fills lost $41.28 while prediction fills gained $44.16; the sample remains too small to establish alpha. Asset-price contracts caused the largest prediction loss.
- **Expected effect:** concentrate new research on literal rule reading, equivalent-event review, and primary news. Reduce concentration and probability-error risk with cash-backed outcomes, half Kelly, 25% position and 35% driver ceilings.
- **Measure:** v2 after-cost NAV and independent completed outcomes, compared separately from the preserved v1 record. V2 starts at deployment, not the archive date.
- **Fund:** `edgecraft-predictions`; fresh $1,000 once, alongside v1 in the same ledger. Retirement appends an event and refuses to strand open inventory.

## 2026-10-17 · Use venue books and recorded fees to test executable edge
- **Why:** buy-side marks bias displayed P&L, flat bps omit nonlinear prediction fees, and equity horizons exclude holding to resolution.
- **Expected effect:** midpoint marks, side-specific depth fills, explicit venue taker fees, and realistic resolution horizons. Apparent edges erased by execution costs should be rejected.
- **Measure:** accepted/dropped sizing audit, fees, spreads, slippage, and after-cost P&L by revision. Scanner rank measures liquidity/spread, not alpha. Live access remains unverified until the local TLS trust issue is repaired.
- **Fund:** v2 only; `prediction_taker_v1` is immutable mandate metadata. Historical flat-bps accounting is preserved. The stock research lab is removed from active source and remains available at `v1-multi-asset`; original playbooks and public images/data are retained.

## 2026-10-17 · Compare funded forecasts with the market and expose revision performance
- **Why:** trade P&L alone cannot separate forecast quality from sizing and luck, and repeated belief refreshes inflate apparent samples.
- **Expected effect:** one first funded forecast per contract; Brier improvement against entry market probability and sampled pre-settlement CLV, with playbook/revision cuts. Missing outcomes remain null. The dashboard scopes all pages and reports to the selected fund.
- **Measure:** `fund-report` prediction-score counts/means and `fund-lineage` NAV segments, labelled recorded/inferred. Sparse closing observations, correlated events, and positions spanning revisions prevent causal conclusions.
- **Fund:** all reports; v2 is the new default when initialized. Source is prepared for explicit deployment; runtime history is not migrated or rewritten by source edits.


## 2026-10-17 · Verify current venue formats before release
- **Why:** live Kalshi CPI tickers contain decimal points, and Fed/CPI series use `quadratic_with_maker_fees`; default market discovery is dominated by multivariate combinations.
- **Expected effect:** parse decimal strike IDs, use the same quadratic taker curve for series that also charge maker fees, and exclude combos from scanner listings. Empty books remain rejected.
- **Measure:** fixture coverage for both quadratic fee types and read-only live listing/book/fee checks on both venues. Initial TLS errors no longer reproduced in the development environment; deployed access still requires verification.
- **Fund:** v2. Five v1 Codex automations were paused for explicit cutover; the runtime monitor, checkout, and ledger were not changed.


## 2026-10-17 · Keep generated snapshots out of runtime source status
- **Why:** writing v2 charts under unignored `assets/` would stamp later cycles dirty despite unchanged trading code and complicate deployment.
- **Expected effect:** scheduled snapshots write `state/prediction-progress.svg`; public v1 images stay preserved.
- **Measure:** runtime remains clean after chart/report generation; cycle provenance records the deployed commit without a generated-file dirty flag.
- **Fund:** v2.

## 2026-10-17 · Spend discovery requests on supported, potentially liquid contracts
- **Why:** runtime discovery encountered team-labelled Polymarket outcomes and Kalshi listings with no indicative bid/ask. They consumed the bounded book budget without producing usable research candidates.
- **Expected effect:** restrict binary discovery to YES/NO labels, normalize their case, and exclude obviously unusable listing spreads before fetching depth. Fresh books still own execution; indicative metadata never becomes a fill.
- **Measure:** scanner exclusion reasons, book-attempt coverage, and sourced candidates per session. No fees, limits, or access checks are weakened.
- **Fund:** v2.

## 2026-10-17 · Patch dashboard dependencies before local deployment
- **Why:** the previous Next.js lock carried critical advisories; a fresh install also revealed vulnerable transitive build dependencies.
- **Expected effect:** Next.js and its ESLint config move to 16.3.8, with compatible transitive updates. Production dependency audit must pass, followed by lint, tests, and build.
- **Measure:** `npm audit --omit=dev` and the dashboard release checks. Five remaining development-tool advisories originate in unpatched `braces` through the linter's glob dependency; they are not resolved by forcing an older Next ESLint major. Recheck when upstream publishes a fix.
- **Fund:** dashboard only; no trading math changes.

## 2026-10-17 · Install a persistent, localhost-only read-only dashboard
- **Why:** deploying the research runtime alone leaves the new fund views unavailable after the temporary development server stops.
- **Expected effect:** a user LaunchAgent serves the built dashboard at `127.0.0.1:3000`, restarts it on failure/login, and reads the authoritative shared ledger without write access.
- **Measure:** HTTP checks for v1/v2 views, SQLite read-only smoke, and LaunchAgent state. Logs remain private under `state/logs/`.
- **Fund:** read-only views of both eras.
