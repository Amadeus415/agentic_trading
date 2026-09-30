# How the fund learns

Read `review` in `make fund-context` or `state/fund-report.json`. A review is due one day after initialization/the last completed review, or after 10 additional completed positions, whichever comes first (`trading.review_days` and `trading.review_closed_trades` in the active config). Trading sessions check the trigger; the Sunday evolution task is a regular fallback. Time passing alone does not run a model: a Codex task must execute the review.

## One review

1. Run `make fund-report-file`, `make fund-context`, and `uv run edgecraft fund-postmortem-schema`.
2. Read closed-trade results, calibration, recent journals, current playbooks, and their statuses. Distinguish economic P&L from repeated observations of the same belief.
3. Write one schema-valid `state/weekly-postmortem.json`. Explain what worked, what failed, and the smallest supported experiment. No change is a valid result when evidence is weak.
4. Apply once:

```bash
uv run edgecraft fund-evolve \
  --config examples/fund.mandate.aggressive.json \
  --ledger state/edgecraft-aggressive.db \
  --postmortem state/weekly-postmortem.json
make fund-verify
make fund-report-file
```

Stop on failure. Never modify a failed review to get it accepted. Exact successful replay is a no-op; proposal IDs cannot be reused.

## What can change

| Proposal kind | Allowed patch fields |
| --- | --- |
| `research_prompt_edit` | `prompt` |
| `universe_edit` | `universe` |
| `playbook_param` | `trigger`, `entry_rule`, `exit_rule`, `sizing_hints` |
| `new_playbook` | `thesis`, `universe`, `trigger`, `entry_rule`, `exit_rule`, `sizing_hints`, `required_evidence_types`, `prompt` |
| `retire_playbook` | Empty patch |

The parent is `playbook_id`. Each non-retirement proposal creates a separate deterministic experiment ID in the ledger; `fund-context` returns its effective spec and prompt. Use that ID in hypotheses and orders. The parent keeps its rules and record. Runtime tasks never edit tracked files.

Every valid prompt, universe, rule, or new-playbook proposal can enter a funded forward paper experiment without lab artifacts. `backtestable` describes whether a backtest is possible; it does not require one. New versions start with no inherited trades and a 60% NAV incubation ceiling. All strategy ceilings share the fund's gross budget, so many proposals cannot manufacture capital.

When artifacts are supplied, they must show positive walk-forward out-of-sample return and deflated Sharpe probability of at least 0.95. Passing artifacts add a `validated` transition before incubation. Failing artifacts leave the version `proposed` with zero budget. Do not omit a known failed validation to repackage the same idea as a fresh experiment. Historical shadow versions retain their zero budget; propose a new version to forward-test a revised idea.

The allocator uses each version's most recent 20 completed positions. After 10 results, positive mean after-cost P&L promotes an incubating version to `active`; nonpositive mean freezes an incubating or active version. Active versions share budget by mean P&L × √sample count, capped at 120% NAV each. These are aggressive experimental heuristics, not confidence claims. Partial exits count once, when the position becomes flat.

Frozen or retired versions receive no new entries. Existing inventory keeps its normal exits. A review can propose a replacement version with a new record. All proposals are checked before one atomic event stores the effective versions and transitions. `fund-context` and sizing derive current allocations from the same outcomes; `fund-evolve` persists lifecycle transitions.

Artifact validation checks result fields, not an independently rerun experiment. Never fabricate artifacts or treat synthetic returns as market evidence. A review with `proposals: []` is valid when no useful change is supported. When measured failures identify a concrete adjustment, prefer one testable change over waiting for statistical certainty.

The original bankroll, initialized mandate, costs, accounting, and broker boundary remain outside this loop. `trading` settings change through tested source releases and are stored in each sized cycle's audit. Read [Design](DESIGN.md) for how trade, manage, and learn fit together.
