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


## 2026-10-17 · Check the dashboard release in CI
- **Why:** Python-only CI did not cover the read-only UI or its vulnerable dependency lock.
- **Expected effect:** every release runs a locked Node 22 install, lint, tests, build, and production dependency audit alongside Python/security checks.
- **Measure:** the dashboard CI job must pass. Development-only upstream advisories remain documented separately.
- **Fund:** dashboard only.


## 2026-10-17 · Deploy v2 without rewriting the v1 record
- **Why:** the tested prediction-only experiment needs an authoritative runtime and updated schedules, while the original track record must remain intact.
- **Expected effect:** `main` deploys by fast-forward; v1 retires flat at $1,020.41 after 96 cycles, and v2 starts at $1,000 with no inherited trades. Private state and SQLite backups precede cutover.
- **Measure:** both funds verify; every original v1 cycle and event matches its backup (plus one retirement event). The runtime stays clean, the localhost dashboard serves both funds, and only v2 research/evolution prompts resume.
- **Fund:** v1 archive and v2 active. No forced trading cycle was applied during deployment.


## 2026-10-18 · Aim discovery at fast, lightly watched contracts
- **Why:** the first v2 shortlist was 20 of Polymarket's most-traded markets (Fed decision, midterms, Ballon d'Or) and no Kalshi contracts: ranking by depth ÷ spread selected the most efficiently priced markets, where an LLM is least likely to have an edge. Holding up to a year also leaves $1,000 idle.
- **Expected effect:** discovery covers four horizon windows on both venues; rank is attention ÷ days to resolution, with depth only a fill constraint. Candidates carry `annualized_if_wins` and the favorite-bias probability; `catalysts` lists contracts resolving within 48 hours; `event_flags` finds mutually exclusive outcomes whose YES bids sum above $1. Stalled reads retry once; HTTP, TLS, and access errors still fail closed.
- **Measure:** scan coverage, catalyst counts, and the venue mix of candidates; v2 holding time and turnover in `fund-report`.
- **Fund:** `edgecraft-predictions` research; `edgecraft-baseline` uses the same discovery.

## 2026-10-18 · Learn from scored forecasts and size on measured trust
- **Why:** promotion needed 10 closed trades per playbook, which takes months at long horizons, and 10 binary outcomes cannot separate skill from luck (v1's per-trade interval was −$19 to +$21). Sizing applied half Kelly to the model's raw probability; v1's largest loss was a 16%-of-NAV longshot.
- **Expected effect:** every researched market gets a forecast stamped with the code-owned price. Settlements (and, earlier, market drift at least 12 hours after the forecast, counted at half weight) fit a trust λ per playbook; sizing bets on `market + λ × (p_win − market)`, so a playbook without measured skill cannot size up. Edges below a 30% annualized hurdle drop, and the fastest edges are funded first. The allocator promotes at estimated λ ≥ 0.10 and freezes at λ ≤ 0.05 (settled evidence only) after 30 scored forecasts; realized losses remain a kill switch. The exit-fee reserve is now expected (stop for losers, target for winners) rather than worst case at 50¢, which no longer rejects near-certain contracts held to settlement. Positions keep 5% headroom under the 25% cap so later entries' spread cannot block them.
- **Measure:** `forecast_skill` in `fund-report`/`fund-context`: resolved and drift counts, skill vs market Brier, trust per playbook and category, and head-to-head results for experiment versions. Sizing audits record trust, believed p_win, and annualized return per order.
- **Fund:** `edgecraft-predictions`. The immutable mandate is unchanged; `trading` gains `prior_trust`, `trust_prior_weight`, `promotion_forecasts`, `min_annualized_return`, and `min_depth_usd`.

## 2026-10-18 · Add a code-only control fund
- **Why:** without a no-model baseline, LLM research cannot be shown to add value. Two structural edges need no model: the favorite-longshot bias, and mutually exclusive outcomes whose YES bids sum above $1.
- **Expected effect:** `edgecraft-baseline` ($1,000, same mandate, same ledger) buys favorites priced 80–98.5¢ that resolve within 21 days when `logistic(γ·logit(mid))` clears the ask and fees, and buys equal NO on every leg of a flagged exclusive event when the asks still lock in 1¢ per basket. Quarter Kelly, 10% position and 20% event caps. Every scan logs markets' own prices so settled outcomes refit γ (prior 1.15, weight 100 settlements). The five-minute monitor runs it at most every 30 minutes and writes cycles only when it buys.
- **Measure:** baseline NAV versus the research fund on the dashboard; `favorite_bias.fitted_gamma` and resolved count in `state/fund-report-edgecraft-baseline.json`. If γ fits near 1, the favorite edge is absent and the strategy stops finding trades.
- **Fund:** `edgecraft-baseline`, initialized by the first monitor run after deployment.

## 2026-10-18 · Remove retired stock-era code
- **Why:** v1 is retired; stock/crypto quote adapters, NAV backfill from stock history, stock-hours queueing, short-stock sizing, backtest-artifact validation, and the DCA research example no longer run on any live path.
- **Expected effect:** less code on the money path. Ledger accounting still replays every v1 cycle, and v1 reports still generate.
- **Measure:** `make validate`; `fund-verify` for both eras.
- **Fund:** none; no trading behavior changes.

## 2026-10-18 · Move research and reviews from Codex to Claude Code
- **Why:** the fund's agent runs move to Claude Code. Codex automations and their PreToolUse hook were the only Codex dependency.
- **Expected effect:** five Claude Code local scheduled tasks (four daily research sessions at the same Pacific times, one Sunday review) replace the five Codex automations and follow `docs/SCHEDULED_TASKS.md`. `.claude/settings.json` blocks broker order tools in every session. Accounting, sizing, the monitor, and cycle keys are unchanged.
- **Measure:** cycles record the Claude model in `runtime.model`; one accepted cycle per session key, as before. A skipped run shows as a missing session key in `make fund-show`.
- **Fund:** `edgecraft-predictions`. The Codex automations are paused once the Claude tasks exist, not deleted, so they can be resumed if needed.

## 2026-10-18 · Size research bets about four times larger
- **Why:** trust (0.35) and half Kelly both discounted every belief for the same reason, unproven skill, so the fund bet about 17% of what its own belief justified. A 20-point edge on a 50¢ contract got $61 of $1,000, and the end-to-end run held cash on mild beliefs. That pace cannot compound.
- **Expected effect:** one discount instead of two. Prior trust rises to 0.60 and Kelly to full on the trust-shrunk belief, so the same 20-point edge gets about $224. The shared-driver cap rises from 35% to 50%, the incubation sleeve from 35% to 50%, and an active sleeve may take the whole budget. The research prompt asks for honest, unhedged probabilities and a belief on every favored contract. The control fund moves to half Kelly with 15% position and 30% event caps. Measured trust still takes over as forecasts settle: a playbook without skill still shrinks toward zero, and the mandate's 25% position cap and 50% drawdown limit are unchanged.
- **Measure:** gross exposure and turnover in `fund-report`; sizing audits show `kelly_weight` and `trust` per order. Losses are larger per wrong call: watch drawdown against the 50% limit.
- **Fund:** `edgecraft-predictions` and `edgecraft-baseline`. Mandates are unchanged; only `trading` settings move.

## 2026-10-18 · Start research sessions from launchd instead of the desktop app
- **Why:** `edgecraft-predictions` recorded zero cycles in its first 30 hours. The desktop-app routines were never created, and they could only fire while the app was open. The fund sat in cash because nothing started a session, not because it found no edge.
- **Expected effect:** two LaunchAgents (`com.edgecraft.claude-research` four times daily, `com.edgecraft.claude-review` Sundays) run headless `claude -p` sessions with the prompts in `docs/SCHEDULED_TASKS.md`, auto permissions, and no MCP connectors. Only the trigger changes: prompts, the broker-tool hook, sizing, the monitor, and cycle keys are unchanged.
- **Measure:** one accepted cycle per session key in `make fund-show`; a missing key with a `state/logs/claude-research-*.log` transcript shows why the run stopped.
- **Fund:** `edgecraft-predictions`.

## 2026-10-19 · Check sized decisions before the ledger, and verify integrity rather than input rules
- **Why:** the first launchd research run (`2026-10-19-session-offhours`) cited evidence without contract-level `instrument_ids`. Sizing built orders by copying the decision, which skips validation, so the ledger accepted three orders that the evidence rule forbids. `fund-verify` then re-ran that rule on replay and crashed. That froze the research fund, and through the monitor it also froze the baseline.
- **Expected effect:** sizing drops entries without contract-specific evidence (`no_instrument_evidence`) and validates the final decision before applying it, so a rule break now fails before the ledger. Verify proves the hash chain, request digests, and accounting replay. It reports stored cycles that break today's input rules as `warnings` instead of failing, so a rule change can no longer make an accepted history unverifiable. The research prompt now says to tag evidence per contract.
- **Measure:** `fund-verify` passes for all three funds. `edgecraft-predictions` carries one warning for the cycle above, whose fills (Milan 21°C NO, Lucknow 31°C NO, Shanghai 26°C YES) stand as recorded. `dropped` reasons in sizing audits show any future `no_instrument_evidence`.
- **Fund:** `edgecraft-predictions`; verification changes apply to every fund.
