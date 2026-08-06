# Codex scheduled operation

Use a Codex scheduled task as the wake-up mechanism and Edgecraft as the
authority. Run the task in the local project, not a worktree: the append-only
ledger, runtime artifacts, authenticated Robinhood MCP session, and kill switch
must remain in the persistent checkout.

The machine must be powered on, the ChatGPT desktop app must be running, and
Codex and Robinhood authentication must be current. Scheduled tasks run
unattended, so use the narrowest permission profile that still permits the
network and local state access required by the broker/context providers.

## Daily paper mandate

The schedule is fixed to the checked-in market-day shadow mandate. It allocates
up to `$25` to the simulated portfolio each market weekday, records approved
orders as `paper_trade_recorded` runtime events, and never creates Robinhood
orders. The scheduled entrypoint intentionally has no live-mandate override.

## Single fail-closed wake path

Codex should run **only** the scheduled entrypoint (one shell command). Do not
chain post-cycle performance or execution-quality reports on the critical path;
inspect those later from the CLI when needed.

```bash
./scripts/run_scheduled_cycle.sh
```

Or via Make (same script, shadow default):

```bash
make scheduled-cycle
```

The script runs `health` → `readiness --require-ready` → `cycle` with the fixed
daily paper mandate (`examples/mandate.index-dca.json`).

`health` exits nonzero when `ok` is false. `readiness --require-ready` exits
nonzero when any deterministic check fails. The script never starts a cycle
after a failed gate. A `cycle` result with `ok=false` also exits nonzero;
accepted outcomes such as `not_due`, `held`, `risk_rejected`, and
`shadow_complete` exit zero.

## Durable task prompt

> Operate only in this Edgecraft project. Do not edit source files, policies,
> mandates, hooks, or credentials. Run exactly:
> `./scripts/run_scheduled_cycle.sh`
> If any step fails, stop and report the exact JSON/reasons. Never bypass a
> failed check, retry a run that issued a permit, change capital limits, or place
> any order outside the exact enabled mandate. The scheduled script is
> paper-only and must never be redirected to another mandate.

Run it daily after `10:00 America/New_York`. Weekend wakeups return `not_due`
without model work; they still verify health. Weekday approved proposals update
the paper portfolio, while weak or unsafe opportunities are truthfully recorded
as holds or rejections rather than fabricated trades. Edgecraft's cycle key and
ledger lock make repeated wakeups idempotent. Review the first several runs in
the Codex Scheduled inbox.

After a wake, optional operator inspection (not on the critical path):

```bash
uv run edgecraft autonomy-health --ledger state/edgecraft-paper.db
uv run edgecraft runs --ledger state/edgecraft-paper.db --limit 1
uv run edgecraft performance --ledger state/edgecraft-paper.db --mandate-id index_dca
```
