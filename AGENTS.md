# Nightshift

A live benchmark: can an AI agent make money trading prediction markets, and get better at it by rewriting its own code? Start with `README.md`; the spec is `docs/METHODOLOGY.md`.

## Principles

- **Environment vs agent.** The harness (`src/nightshift`) owns market data, fills, fees, accounting, settlement and scoring. Agents own everything in their workspace, including strategy, sizing and their own instructions. Never move strategy into the harness, and never give an agent a way to write outside its workspace.
- **Fills favor the market.** Walk the real book, charge real fees, value at the bid, and refuse what the book can't fill. When in doubt, choose the rule that makes the agent's result less flattering.
- **Measure, don't steer.** Prompts, the seed workspace and the rules are identical across agents. Arms differ in exactly one thing.
- **Versioned and pre-registered.** Any change to what agents face or how they are scored bumps `BENCHMARK_VERSION` and gets a `CHANGELOG.md` entry. Live runs are never patched; log every intervention with `nightshift note`.
- **Simple.** Standard library only at runtime. One ledger per run, one website, one command per job. Prefer deleting code to adding options.
- **Honest numbers.** Report sample sizes and intervals, say when a difference is not distinguishable from luck, and keep simulated results labelled as simulated.

## Working here

- `make check` runs the tests, lint and format check. Run it before every commit.
- Tests use fake venues (`tests/conftest.py`) and never call the network or a model.
- Private state lives in `$NIGHTSHIFT_HOME` (default `~/.nightshift`, never inside this repo): ledgers, workspaces, transcripts.
- Commits are one idea each, with a subject that says why.
