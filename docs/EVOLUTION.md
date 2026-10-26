# How the fund learns

The fund learns from **forecasts**, not just trades. Closed trades arrive slowly and each one is mostly luck; a forecast on any market, scored against that market's own price, arrives in hours and measures skill directly.

## The forecast loop

1. Each research session writes a forecast file (`state/fund-inputs/<key>.forecasts.json`) with a YES probability for every market it researched. `variant` names the playbook or experiment that produced it. Journal beliefs in the trade packet are logged as forecasts too.
2. The session runs `fund-forecast` as soon as the file is written, before any step that can stop it. It stamps each forecast with the **code-owned market price at that moment** and appends it to the hash-chained ledger; the apply step records the file again, which adds only forecasts not yet recorded. Forecasts on already-settled markets are refused. Only the first forecast per market and variant counts, so refreshes never inflate the sample.
3. The five-minute monitor runs `fund-forecast-score`: it records each market's settlement and, for research forecasts, later marks.
4. `forecast_skill` (in `fund-report` and `fund-context`) turns settled forecasts into two numbers per variant:
   - **Trust** (λ) for opinions. With 30+ resolved forecasts (`promotion_forecasts`), λ is the maximum-likelihood fit of `outcome ~ market + λ × (forecast − market)`, and sizing uses the lower end of its 95% profile-likelihood interval. Before that, trust is zero. Skill is the market's Brier score minus the forecast's: positive means the forecasts beat the price.
   - **Fact accuracy** for facts. A fact call is a forecast at ≥ 95% on one side while the market priced that side below 95%. Accuracy is `(wins + 0.95 × 20) / (calls + 20)`, so it starts at 0.95 and each settled call moves it.
   - Later price drift toward a forecast is reported, never used for sizing. In v2, drift and a prior gave unmeasured playbooks trust of 0.6–1.0, and their settled forecasts later fitted at or below zero.
5. Sizing caps a fact at its playbook's fact accuracy and bets an opinion on `market + λ × (p_win − market)`. A playbook with λ = 0 cannot trade opinions, however confident it sounds.

Results are also cut by `category` (a skill map of where the model beats the market) and **head to head**: any two variants that forecast the same 5+ resolved markets get a paired Brier comparison, which removes most of the noise of comparing different markets.

## Lifecycle

A playbook's budget is a cap on how much of NAV it may hold, not a slice of the fund; the mandate's gross limit already keeps experiments from minting capital, and sizing funds the fastest edges first whichever playbook found them.

| Evidence | Status | Budget cap |
| --- | --- | --- |
| Fewer than 30 resolved forecasts | `incubating` | `incubation_weight` (100% NAV) |
| 30+ resolved forecasts | `active` | `active_weight` (100% NAV) |
| 10+ closed trades with nonpositive mean P&L | `frozen` | none (kill switch) |

Forecast skill does not freeze a playbook: zero trust already keeps its opinions out of sizing, and its fact calls are judged by their own record. Frozen or retired versions receive no new entries; existing inventory keeps its normal exits. `fund-evolve` persists allocator transitions.

## One review

A review is due one day after initialization or the last completed review, or after 10 additional completed positions (`trading.review_days`, `trading.review_closed_trades`). Trading sessions check the trigger; the Sunday evolution task is a regular fallback.

1. Run `make fund-report-file`, `make fund-context`, and `uv run edgecraft fund-postmortem-schema`.
2. Read `forecast_skill` (variants, categories, head to head, fact accuracy), closed-trade results, recent journals, and current playbooks. Distinguish economic P&L from repeated observations of the same belief.
3. Write one schema-valid `state/weekly-postmortem.json`. Explain what worked, what failed, and the smallest supported experiment. No change is a valid result when evidence is weak.
4. Apply once:

```bash
uv run edgecraft fund-evolve \
  --config examples/fund.mandate.facts.json \
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

The parent is `playbook_id`. Each non-retirement proposal creates a separate deterministic experiment ID that starts `incubating` with no inherited record; `fund-context` returns its effective spec and prompt. Research sessions then forecast the same markets under the parent and the experiment, so the head-to-head comparison decides which one keeps budget. Runtime tasks never edit tracked files.

## The control fund

`edgecraft-baseline` runs two structural strategies with no model (see [Design](DESIGN.md)). It is the bar the research fund must clear: if the LLM cannot beat a few lines of code, it is costing money. The baseline learns too: every scan logs each market's own price as a `market` forecast, and once those settle the favorite-longshot curve's γ is refit (blended with the `baseline_gamma` prior at a weight of 100 settled markets). Research scans in the same ledger use the fitted γ for `favorite_bias_p`.

The original bankroll, initialized mandate, costs, accounting, and broker boundary remain outside this loop. `trading` settings change through tested source releases and are stored in each sized cycle's audit.
