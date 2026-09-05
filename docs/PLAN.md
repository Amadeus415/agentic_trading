# Edgecraft assessment and next steps

Audited September 4, 2026. The ambition is an active, autonomous fund that grows aggressively, beats the S&P 500, and improves its decisions using a Codex subscription.

The strongest first-principles design is already present: one researcher, one deterministic trading engine, one immutable record, three loops (trade, manage, learn). Keep that structure. The missing ingredient is evidence of a repeatable trading advantage.

## What the audit found

| Area | Finding | Result of this pass |
| --- | --- | --- |
| Trading | Persistent accounting, simulated long/short fills, fees, quote checks, and atomic cycles exist. | Retained the core and its tests. |
| Operations | Four local Codex schedules target a separate clean runtime; the hourly LaunchAgent's latest exit was successful. Runtime and development revisions differed. | Inspected actual settings and ledger; source changes here are not automatically a deployed release. |
| Performance | Runtime NAV $916.66; 16 closed trades; 50% wins; −$5.21 after-cost expectancy; accounting and hash chain pass. | Recorded the dated baseline without claiming profitability. |
| Learning | Proposals recorded statuses but did not change effective research; no weekly-or-trade-count trigger existed. | Added ledger-backed experiment versions and due status to report/context. Reviews apply atomically and replay safely. |
| Sizing | Each order could reuse the whole sleeve budget; existing holdings were absent from driver caps; unknown strategy IDs bypassed allocation; entry/exit fee math omitted one fee. | Count existing inventory and cumulative new entries, reject unknown IDs, charge both sides in the estimate. |
| Benchmark | Dashboard could choose a future inception price and include observations beyond the fund window. Ledger SPY benchmark was unavailable. | Use a prior completed close and exact cutoff; label the chart as a dividend-excluding price proxy. |
| Readiness | Cycle-sampled annualized Sharpe and missing model costs could help produce an optimistic graduation flag. | Automatic live eligibility stays false with an explicit reason. |
| Presentation | Long README, stale roadmap, and a $100k progress panel distracted from actual performance. | Shorter README and agent instructions; dashboard prioritizes benchmark and learning. |

## What limits active trading today

Four starting strategies each receive at most 5% of NAV during incubation. Together that is 20% of NAV, before Kelly and other caps. The mandate's 3× gross limit is a ceiling, not a target or actual allocation. Increasing that ceiling would not fix weak research or create an edge.

The current schedules research at 10:15 and 13:15 Los Angeles time on weekdays, plus Sunday evening. The labels say US open/close, but the close run occurs after the regular equity session. Stocks cannot fill then. There is no Saturday research task. The hourly monitor manages existing positions but does not search for entries. For more opportunities, the next deployment should move the close scan before market close and use daily off-hours crypto research. Validate UTC cycle slots and daylight-saving behavior before changing the schedule.

The monitor samples hourly, so it can miss brief stops and targets. Its equity-hours check handles weekday hours but not exchange holidays or early closes. Public feeds do not establish executable spreads, borrow availability, market impact, or queue position. These are material simulation limits.

## Priorities, with finish lines

1. **Make the experiment reliable.** Deploy the tested source to the runtime, verify the next scheduled session and review, and display missed-session/data-age status. Add a proper exchange calendar and improve observation frequency. Finish when a full week runs without silent missed research, stale fills, or ambiguous failures.
2. **Make beating the S&P measurable.** Persist daily marks for every position and a dividend-aware SPY benchmark over identical dates. Separate trading P&L from allocated subscription/data costs. Replace cycle Sharpe with daily-return statistics; cluster partial exits into independent trades before statistical gates. Finish when CLI and dashboard reproduce the same date-aligned return, drawdown, excess return, and cost totals.
3. **Prove one narrow advantage.** Keep four playbooks as hypotheses, but fund only those with forward evidence. Log researched/rejected candidates so inactivity is diagnosable. Compare fixed sizing with learned sizing on the same realistic outcomes. Finish with a repeatable setup that remains positive after cost on unseen forward data.
4. **Close the experimental loop.** Bind validation artifacts to exact candidate rules, data, and code; rerun validation rather than trusting JSON claims. Add paired shadow scoring and a promotion/rollback decision. Correct for repeated testing and correlated trades. Finish with one autonomous proposal → experiment → measured promotion or retirement, visible in the dashboard.
5. **Evaluate a live pilot separately.** Use six months and 200 independent closed trades as an initial evidence floor, not a guarantee. Require positive after-cost expectancy with uncertainty estimates, dividend-aware benchmark outperformance, acceptable drawdowns, and stable operations. Then add broker-paper reconciliation and execution realism before considering tiny authorized real capital.

## Simplify deliberately

Keep the optional lab isolated; it is useful for validation and should not become another orchestrator. Keep one ledger and derive the dashboard from it and the canonical report. Remove duplicate growth-target presentation and stale operational prose. Avoid an agent swarm, a second portfolio store, or a service framework until a measured need justifies one.

The remaining large `paper_fund.py` is easier to trust with its accounting tests than after a cosmetic rewrite. Split it only when a concrete change needs a smaller boundary. Do not delete audit history or the frozen earlier book to make the project look simpler.

## The resume story

“Built an autonomous paper-trading system using subscription-backed Codex research, deterministic execution and risk controls, an immutable SQLite ledger, scheduled monitoring, and versioned strategy experiments with a benchmark dashboard.”

Support that sentence with a runnable demo, one annotated trade, one rejected decision, one experiment history, and honest forward results. Add market-beating claims only if the record eventually supports them.
