---
name: trading-status
description: >
  Overview of how the Edgecraft paper fund is trading right now — NAV, P&L,
  positions, recent cycles, ledger health, and latest decision. Use when the
  user asks how trading is going, fund status, portfolio performance, paper
  book health, "how's the fund", P&L summary, or runs /trading-status.
---

# Trading status — Edgecraft paper fund overview

Produce a concise, evidence-backed snapshot of the **active $1,000 paper fund**.
All money is simulated. Never imply live brokerage activity.

## Defaults (repo root)

| Item | Path |
|---|---|
| Mandate | `examples/fund.mandate.aggressive.json` |
| Ledger | `state/edgecraft-aggressive.db` |
| Session inputs | `state/fund-inputs/YYYY-MM-DD-session-*.json` |
| Docs | `docs/FUND_ACCOUNTING.md` |

Prefer `make` targets. Equivalent CLI uses the same config/ledger.

## 1. Collect data

Run from the repository root. Capture JSON output:

```bash
make fund-show
make fund-verify
```

`make fund-show` already includes `--history`. Add `--events` when you need the
hash-chain tail:

```bash
uv run edgecraft fund-show \
  --config examples/fund.mandate.aggressive.json \
  --ledger state/edgecraft-aggressive.db \
  --history --events --limit 10
```

If the ledger is missing or commands fail, say the fund is not initialized and
point at `make fund-init` — do not invent numbers.

### Optional depth (only when useful)

- **Latest cycle packet:** take `state.last_cycle_key` from fund-show, then:
  ```bash
  uv run edgecraft fund-cycle \
    --config examples/fund.mandate.aggressive.json \
    --ledger state/edgecraft-aggressive.db \
    --cycle-key <last_cycle_key> --audit
  ```
- **This session's researched input on disk:** run `uv run edgecraft fund-cycle-key` and check that `input_path`; if missing, say this session's packet is not written yet. Older same-day session files may still exist.
- **Do not** start the dashboard or mutate the ledger for this skill.

## 2. Present the overview

Use this structure. Format money as dollars with 2 decimals; percentages with
2 decimals (e.g. `+0.59%`). Keep decimal fidelity from CLI when rounding.

### Header

One line: paper-only fund id, evaluation status from `history` (`measuring` if
fewer than 20 cycles, else `active`), and `as_of` from state.

### Scoreboard

| Metric | Value |
|---|---|
| NAV | current_nav |
| P&L vs $1,000 | profit_and_loss (+/−) |
| Total return | total_return |
| Peak NAV / drawdown | peak from history · max_drawdown (and state.drawdown if non-zero) |
| Cash | state.cash |
| Gross / net exposure | state.gross_exposure · state.net_exposure |
| Cycles | cycle_count (trade_count trades · hold_count holds · N fills) |

### Book

Table of open positions from `state.positions`:

| Instrument | Class | Qty | Mark | Mkt value | Unrealized P&L | Avg entry |
|---|---|---:|---:|---:|---:|---:|

If empty: say fully in cash.

### Recent activity

From `history.history` (newest first, last 5) and/or `events`:

- cycle_key · action (trade/hold) · NAV · fill_count · as_of
- One-line note on whether the last action was trade or hold

If you loaded `fund-cycle` for the latest cycle, add a short **Latest thesis**
(1–3 sentences from `decision.thesis`) and order summary (side · instrument · qty).

### Health

From `fund-verify` (not from fund-show):

- chain_ok · accounting_ok · overall ok
- Flag any false values or non-empty details loudly

### Read of the tape (brief)

2–4 bullets max:

- Whether the book is up/down vs the $1,000 start and why (mark moves vs fills)
- Concentration: largest position weight ≈ market_value / nav
- Cash buffer and deployment (~1 − cash/nav)
- Caveat if `history.status` is `measuring`: sample is too short to claim skill

Quote the performance `interpretation` when status is `measuring`.

## 3. Rules

- **Source of truth is the ledger CLI**, not the dashboard, caches, or chat memory.
- **Paper only.** Label every money figure as simulated if there is any ambiguity.
- **No skill claims from raw return** on a short history.
- **No mutations:** never run fund-run, fund-init, or the scheduled cycle unless
  the user explicitly asks outside this skill.
- **No secrets:** do not print env credentials, OAuth, or personal account data.
  This path is paper-fund only.
- If the user asks for a **deeper dive** on one day, use `fund-cycle --audit`
  for that `cycle_key` rather than dumping full event payloads by default.

## 4. Failure modes

| Situation | Response |
|---|---|
| Ledger missing | Fund not capitalized; suggest `make fund-init` |
| Verification not ok | Show failing checks first; do not soft-pedal |
| Zero cycles | Capitalized but no decisions applied yet |
| Commands error | Paste the error; stop rather than guess |

## Quick one-liner mode

If the user only wants a pulse check ("quick", "one line", "tldr"):

```text
edgecraft-aggressive · paper · NAV $X (P&L +/−$Y, +Z%) · N pos · last cycle KEY (trade|hold) · ledger ok|FAIL · as_of …
```

Still run `make fund-show` and `make fund-verify` before answering.
