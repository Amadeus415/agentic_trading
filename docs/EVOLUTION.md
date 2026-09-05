# How the fund learns

Read `review` in `make fund-context` or `state/fund-report.json`. A review is due seven days after initialization/the last completed review, or after 20 additional closed trades, whichever comes first. Trading sessions check the trigger; the Sunday evolution task is a regular fallback. Time passing alone does not run a model: a Codex task must execute the review.

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

Backtestable proposals need positive walk-forward out-of-sample results and deflated Sharpe probability of at least 0.95 in lab artifacts. They enter a 5% incubation sleeve. Non-backtestable edits enter shadow with zero capital. Record their sourced hypotheses for later evaluation; do not label them live-tested. Failed validations remain proposed with no budget. Retirement removes the entry budget; existing inventory still needs its normal exits.

All proposals are validated before a single atomic review event stores the review, effective versions, and transitions. Allocation can promote an incubating version after 20 closed trades with a positive approximate lower confidence bound, or freeze/retire weak versions. These are heuristics, not proof of persistent alpha. The event trail preserves every version.

## Boundaries still needing work

Artifact validation currently checks result fields, not a cryptographically bound, independently rerun experiment. Do not fabricate artifacts or use synthetic returns as market evidence. Shadow versions do not yet have an automatic promotion evaluator. A reviewed proposal is not proof that the system improved.

Accounting, fees, mandate limits, bankroll, and broker access are outside this loop. Changes to the software itself happen as normal reviewed, tested code changes.
