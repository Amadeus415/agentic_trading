# Dashboard

Read-only Next.js UI over the paper-fund SQLite ledger. It never places orders
or mutates the ledger. Do not add live APIs, broker adapters, or write paths.

Default database: `state/edgecraft-aggressive.db` (override with `EDGECRAFT_FUND_DB`).
The paper-fund product rules in the repository root `AGENTS.md` still apply.

Surface the ledger the CLI already stores: journals, instrument hypotheses,
growth-objective telemetry, cycle audit sidecars, and the compact fund brain.
Do not invent a second accounting engine or a live broker path.
