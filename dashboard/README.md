# Edgecraft Dashboard

Read-only Next.js UI over the paper-fund SQLite ledger
(`state/edgecraft-aggressive.db`). It never places orders or mutates the ledger.

## Setup

From the repository root:

```bash
make dashboard
```

Or from this directory:

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Environment

Create or keep `.env.local` in this directory:

```bash
EDGECRAFT_FUND_DB=../state/edgecraft-aggressive.db
```

Path is resolved relative to the process working directory (usually
`dashboard/`). Override with an absolute path if needed. Defaults to the same
relative path when unset.

## Build / start

```bash
npm run build
npm start
```

## DB smoke (no Next import)

From `dashboard/`:

```bash
node scripts/smoke-db.mjs
```

Uses `better-sqlite3` only. Resolves `EDGECRAFT_FUND_DB` (or the default relative
path) and prints `fund_id`, cycle count, and fill count.

## Pages

| Route | Purpose |
|:--|:--|
| `/` | Fund overview: NAV vs SPY-normalized chart, summary stats, open positions |
| `/trades` | Paper fills and cycle decision metadata (thesis, action, digests) |

Pages read the SQLite ledger directly (`src/lib/fund.ts`). There is no JSON API
and no write path.
