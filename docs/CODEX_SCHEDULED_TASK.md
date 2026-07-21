# Codex scheduled operation

Use a Codex scheduled task as the wake-up mechanism and Edgecraft as the
authority. Run the task in the local project, not a worktree: the append-only
ledger, runtime artifacts, authenticated Robinhood MCP session, and kill switch
must remain in the persistent checkout.

The machine must be powered on, the ChatGPT desktop app must be running, and
Codex and Robinhood authentication must be current. Scheduled tasks run
unattended, so use the narrowest permission profile that still permits the
network and local state access required by the broker/context providers.

## Durable task prompt

Use this prompt for the explicitly armed mandate:

> Operate only in this Edgecraft project. Do not edit source files, policies,
> mandates, hooks, or credentials. First run `uv run edgecraft health
> --real-data-symbol SPY --ledger state/edgecraft.db`. If health fails, do not
> run a cycle and report the exact reasons. Then run `uv run edgecraft readiness
> --mandate state/mandates/aggressive-market-day-live.json --ledger
> state/edgecraft.db --require-ready`. If readiness fails, do not run a cycle
> and report the exact reasons. If it passes, run `uv run edgecraft cycle
> --mandate state/mandates/aggressive-market-day-live.json --ledger
> state/edgecraft.db`. Then run `uv run edgecraft autonomy-health --ledger
> state/edgecraft.db` and `uv run edgecraft runs --ledger state/edgecraft.db
> --limit 1`. Report
> the run ID, terminal status, decision, violations or warnings, whether any
> permit was issued, broker reconciliation status, and kill-switch state. Never
> bypass a failed check, retry a run that issued a permit, change capital limits,
> or place any order outside the exact enabled mandate.

Run it once each weekday shortly after the mandate's configured decision time.
Edgecraft's cycle key and ledger lock make repeated wakeups idempotent, while a
weekday cadence lets a missed wake-up recover on a later weekday. Review the
first several scheduled runs in the Codex Scheduled inbox.

The checked-in examples/mandate.index-dca.json remains the safe shadow
alternative. Substitute it in the prompt when validating scheduling without
live broker authority.
