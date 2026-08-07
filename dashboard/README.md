# Edgecraft Dashboard

Read-only Next.js UI over the paper-fund SQLite ledger (`state/edgecraft-fund.db`).
It never places orders or mutates the ledger.

## Setup

```bash
cd dashboard
npm install
```

## Environment

Create or keep `.env.local` in this directory:

```bash
EDGECRAFT_FUND_DB=../state/edgecraft-fund.db
```

Path is resolved relative to the process working directory (usually `dashboard/`).
Override with an absolute path if needed. Defaults to the same relative path when unset.

## Develop

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

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

Uses `better-sqlite3` only. Resolves `EDGECRAFT_FUND_DB` (or the default relative path) and prints `fund_id`, cycle count, and fill count.

## Pages

| Route | Purpose |
|:--|:--|
| `/` | Fund overview: NAV vs SPY-normalized chart, summary stats, open positions, recent cycles |
| `/trades` | Paper fills and cycle decision metadata (thesis, action, digests) |

## API (JSON, Node.js runtime)

| Route | Purpose |
|:--|:--|
| `GET /api/funds` | List funds |
| `GET /api/funds/[fundId]` | Fund detail + latest state |
| `GET /api/funds/[fundId]/cycles` | Cycle history |
| `GET /api/funds/[fundId]/performance` | NAV series |
| `GET /api/funds/[fundId]/trades` | Flattened fills |

All API routes and data pages use `export const runtime = "nodejs"` because they load `better-sqlite3`.
