import {
  formatPct,
  formatQty,
  formatTs,
  formatUsd,
} from "@/components/format";
import { PerformanceChart } from "@/components/performance-chart";
import { StatCard, type StatDeltaTone } from "@/components/stat-card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { fetchSpyBenchmarkSeries } from "@/lib/benchmark";
import {
  buildNavSeries,
  extractFillsFromCycles,
  getLatestState,
  listCycles,
  listFunds,
  normalizeSeriesTo100,
  summaryMetrics,
} from "@/lib/fund";
import type { Position } from "@/lib/types";
import { cn } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function num(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

function toneForSigned(value: number): StatDeltaTone {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "neutral";
}

function openPositions(positions: Position[]): Position[] {
  return positions.filter((p) => num(p.quantity) !== 0);
}

function pnlClass(value: number): string {
  if (value > 0) return "text-success";
  if (value < 0) return "text-danger";
  return "text-muted-foreground";
}

export default async function OverviewPage() {
  const funds = listFunds();
  const fund = funds[0] ?? null;

  if (!fund) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
        <section className="rounded-lg border border-border bg-card px-4 py-10 text-center">
          <p className="text-sm font-medium text-foreground">No funds found</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Initialize the paper fund ledger, then refresh this page.
          </p>
        </section>
      </div>
    );
  }

  const cycles = listCycles(fund.fund_id);
  const state = getLatestState(fund.fund_id);
  const navSeries = buildNavSeries(fund, cycles);
  const fundSeries = normalizeSeriesTo100(navSeries);
  const trades = extractFillsFromCycles(cycles);
  const positions = openPositions(state?.positions ?? []);

  const startAsOf = navSeries[0]?.as_of ?? fund.created_at;
  const endAsOf =
    navSeries[navSeries.length - 1]?.as_of ??
    state?.as_of ??
    new Date().toISOString();

  let benchmarkSeries: Awaited<
    ReturnType<typeof fetchSpyBenchmarkSeries>
  > = null;
  let benchmarkFailed = false;
  try {
    benchmarkSeries = await fetchSpyBenchmarkSeries(startAsOf, endAsOf);
    if (!benchmarkSeries || benchmarkSeries.length === 0) {
      benchmarkFailed = true;
      benchmarkSeries = null;
    }
  } catch {
    benchmarkFailed = true;
    benchmarkSeries = null;
  }

  const metrics = summaryMetrics(navSeries, state?.positions ?? [], {
    cash: state?.cash,
    peakNav: state?.peak_nav,
    drawdown: state?.drawdown,
    tradeCount: trades.length,
  });

  const grossExposure = num(state?.gross_exposure);
  const asOf = state?.as_of ?? endAsOf;
  const returnTone = toneForSigned(metrics.totalReturnPct);
  const drawdownTone: StatDeltaTone =
    metrics.drawdown > 0 ? "negative" : "neutral";

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      {/* Header */}
      <header className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate font-mono text-base font-medium tracking-tight text-foreground tabular-nums">
              {fund.fund_id}
            </h2>
            <Badge variant="outline" className="font-mono text-[10px]">
              paper
            </Badge>
          </div>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Paper fund · $1,000 bankroll
          </p>
        </div>
        <p className="font-mono text-xs text-muted-foreground tabular-nums">
          as of {formatTs(asOf)}
        </p>
      </header>

      {/* Stat row */}
      <section
        aria-label="Fund metrics"
        className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7"
      >
        <StatCard
          label="NAV"
          value={formatUsd(metrics.currentNav)}
          hint="Mark-to-market"
        />
        <StatCard
          label="Cash"
          value={formatUsd(metrics.cash)}
          hint="Uninvested"
        />
        <StatCard
          label="Total return"
          value={formatPct(metrics.totalReturnPct, { alreadyPercent: true })}
          deltaTone={returnTone}
          hint="Since inception"
        />
        <StatCard
          label="Drawdown"
          value={formatPct(metrics.drawdown)}
          deltaTone={drawdownTone}
          hint="From peak NAV"
        />
        <StatCard
          label="Gross exposure"
          value={formatUsd(grossExposure)}
          hint="Long + short"
        />
        <StatCard
          label="Open positions"
          value={String(metrics.positionCount)}
          hint="Non-zero lots"
        />
        <StatCard
          label="Trade count"
          value={String(metrics.tradeCount)}
          hint="Fills to date"
        />
      </section>

      {/* Main chart */}
      <section
        aria-label="Performance chart"
        className="flex flex-col rounded-lg border border-border bg-card"
      >
        <div className="flex flex-col gap-1 border-b border-border px-3.5 py-2.5 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
                Series
              </span>
              <h2 className="text-sm font-medium text-foreground">
                Fund vs S&amp;P 500
              </h2>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              SPY is the proxy; both series normalized to 100 at fund inception.
            </p>
          </div>
          <div className="flex items-center gap-3 pt-1 font-mono text-[10px] text-muted-foreground uppercase">
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="inline-block size-1.5 rounded-full bg-indigo-400"
              />
              Edgecraft
            </span>
            {!benchmarkFailed ? (
              <span className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="inline-block size-1.5 rounded-full bg-zinc-500"
                />
                S&amp;P 500
              </span>
            ) : null}
          </div>
        </div>

        {benchmarkFailed ? (
          <div
            role="status"
            className="border-b border-border bg-amber-500/10 px-3.5 py-2 text-xs text-amber-200/90"
          >
            Benchmark unavailable — showing fund NAV only (SPY fetch failed or
            returned no data).
          </div>
        ) : null}

        <div className="px-2 pt-2 pb-3 sm:px-3">
          <PerformanceChart
            fundSeries={fundSeries}
            benchmarkSeries={benchmarkSeries}
            height={360}
          />
        </div>
      </section>

      {/* Positions */}
      <section
        aria-label="Positions"
        className="flex flex-col rounded-lg border border-border bg-card"
      >
        <div className="flex items-center justify-between border-b border-border px-3.5 py-2.5">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
              Holdings
            </span>
            <h2 className="text-sm font-medium text-foreground">
              Current positions
            </h2>
          </div>
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {positions.length} open
          </span>
        </div>

        {positions.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-4 py-10">
            <p className="text-center text-sm text-muted-foreground">
              No open positions — cash only.
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-3.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Instrument
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Class
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Qty
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Avg entry
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Mark
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Mkt value
                </TableHead>
                <TableHead className="pr-3.5 text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Unrealized
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.map((p) => {
                const upnl = num(p.unrealized_pnl);
                return (
                  <TableRow key={p.instrument_id}>
                    <TableCell className="pl-3.5 font-mono text-sm font-medium tabular-nums">
                      {p.instrument_id}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="secondary"
                        className="font-mono text-[10px] capitalize"
                      >
                        {p.asset_class || "—"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm tabular-nums">
                      {formatQty(p.quantity)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm tabular-nums">
                      {formatUsd(p.average_entry)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm tabular-nums">
                      {formatUsd(p.mark_price)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm tabular-nums">
                      {formatUsd(p.market_value)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "pr-3.5 text-right font-mono text-sm tabular-nums",
                        pnlClass(upnl),
                      )}
                    >
                      {formatUsd(p.unrealized_pnl, { signed: true })}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </section>
    </div>
  );
}
