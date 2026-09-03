# Dashboard

Read-only Next.js UI over the paper-fund SQLite ledger. It never places orders
or mutates the ledger. Do not add live APIs, broker adapters, or write paths.

Default database: `state/edgecraft-aggressive.db` (override with `EDGECRAFT_FUND_DB`).
The paper-fund product rules in the repository root `AGENTS.md` still apply.

Surface the ledger the CLI already stores: journals, instrument hypotheses,
growth-objective telemetry, cycle audit sidecars, and the compact fund brain.
Do not invent a second accounting engine or a live broker path.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
