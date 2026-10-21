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
npm ci
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

| Route | Label | Purpose |
|:--|:--|:--|
| `/` | Overview | Chart against the S&P 500, fund value, open then closed positions, recent decisions |
| `/positions/[instrumentId]` | | One contract: holding or after-fee result, latest forecast, every trade with its decision |
| `/trades` | Trades | Simulated fills and settlements; click a row for its details and decision |
| `/cycles` | Decisions | Every completed decision, newest first |
| `/cycles/[cycleKey]` | | Reasoning, forecasts, orders, fills, sources, risk checks, provenance |
| `/attribution` | Scorecard | After-cost results, forecast skill and trust per playbook, calibration, code versions |
| `/brain` | Memory | What the next session is told: activity, notes, outcomes, traded contracts |

The design is light and thin-lined with one typeface (Manrope via `next/font`).
Color carries meaning only: blue for the fund, dashed grey for the S&P 500,
green and red for money gained or lost. Prediction-market prices show in cents,
and contracts are named from the researcher's own claim about them.

Pages read the SQLite ledger directly (`src/lib/fund.ts`). There is no JSON API
and no write path. Journals, the growth objective, and the fund brain are
derived from the same immutable cycle rows the CLI uses.

The SPY chart is a price-return proxy, excluding dividends. It uses the last completed daily close known at fund inception and no prices after the fund observation cutoff. Daily closes become available at a conservative 21:00 UTC cutoff; this is not an intraday total-return comparison. Run `npm test` for benchmark regression checks.

For a development dashboard over the separate runtime, set `EDGECRAFT_FUND_DB` to its absolute ledger path. `EDGECRAFT_FUND_REPORT` can point at a separately generated report; otherwise the dashboard reads `fund-report.json` beside the ledger. The report is a timestamped snapshot and must be regenerated after trades or reviews.


The fund selector scopes every page to one fund via `?fund=<id>`. V2 is the default when initialized; an unknown ID shows an empty view rather than another fund. Attribution reads `fund-report-<fund_id>.json` beside the database, falling back to `fund-report.json` only when its embedded `fund_id` matches. Generate the v1 report with `edgecraft fund-report --config examples/fund.mandate.aggressive.json --output state/fund-report-edgecraft-aggressive.json`. Python produces all lineage and forecast-score math; the dashboard only displays it.
