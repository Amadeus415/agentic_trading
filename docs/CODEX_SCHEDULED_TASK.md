# Codex scheduled operation

Use a Codex scheduled task as the wake-up mechanism and Edgecraft as the
authority. Run the task in the local project, not a worktree: the append-only
ledger, runtime artifacts, authenticated Robinhood MCP session, and kill switch
must remain in the persistent checkout.

The machine must be powered on, the ChatGPT desktop app must be running, and
Codex and Robinhood authentication must be current. Scheduled tasks run
unattended, so use the narrowest permission profile that still permits the
network and local state access required by the broker/context providers.

## Default: shadow mandate

Default the schedule to the checked-in shadow example so wakeups never arm live
broker authority by accident. Substitute a separately versioned live mandate
only after the account owner has explicitly armed it.

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

The script runs `health` → `readiness --require-ready` → `cycle` with the shadow
example mandate by default (`examples/mandate.index-dca.json`). Override only
when live is explicitly armed:

```bash
MANDATE=path/to/armed-live-mandate.json ./scripts/run_scheduled_cycle.sh
```

`health` exits nonzero when `ok` is false. `readiness --require-ready` exits
nonzero when any deterministic check fails. The script never starts a cycle
after a failed gate. On a live wake, `cycle` re-reconciles any unresolved
placed orders before new observe/proposal work.

## Durable task prompt

> Operate only in this Edgecraft project. Do not edit source files, policies,
> mandates, hooks, or credentials. Run exactly:
> `./scripts/run_scheduled_cycle.sh`
> If any step fails, stop and report the exact JSON/reasons. Never bypass a
> failed check, retry a run that issued a permit, change capital limits, or place
> any order outside the exact enabled mandate. For an explicitly armed live
> mandate only, set `MANDATE=path/to/armed-live-mandate.json` for that single
> script invocation.

Run it daily shortly after the mandate's configured decision time. Weekend
wakeups return `not_due` without model or broker work; they still verify health.
Edgecraft's cycle key and ledger lock make repeated wakeups idempotent, while
the daily cadence makes missed or degraded runs visible. Review the first
several scheduled runs in the Codex Scheduled inbox.

After a wake, optional operator inspection (not on the critical path):

```bash
uv run edgecraft autonomy-health --ledger state/edgecraft.db
uv run edgecraft runs --ledger state/edgecraft.db --limit 1
uv run edgecraft performance --ledger state/edgecraft.db --mandate-id weekly_index_dca
```
