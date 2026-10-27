# Security

## Paper money only

Nightshift never places a real order. `venues.py` calls only public, unauthenticated read endpoints of Polymarket and Kalshi. There is no broker, wallet, API key or order endpoint anywhere in the code, and there won't be one.

## Agent containment

Agent sessions run Claude Code in its OS sandbox with settings the harness passes on the command line:
- Writes are allowed only in the agent's workspace.
- Reads of the benchmark's records, the built site and other agents' workspaces are denied.
- The only network path to the exchange is the run's own Unix socket. Escaping the sandbox is disabled.
- No user settings, project settings, MCP servers or auto-memory are loaded.

Ledgers are append-only (SQLite triggers) and hash-chained (`nightshift verify`).

If you find a way for an agent to change its own ledger, read another agent's files, or reach anything outside its workspace, please report it privately through GitHub's security advisories rather than in an issue.

## Private data

`var/` holds ledgers, agent workspaces and session transcripts. It is git-ignored. Read transcripts before publishing them.
