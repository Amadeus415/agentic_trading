import Link from "next/link";

import {
  actionBadgeClass,
  cycleHref,
  num,
  openPositions,
  pnlClass,
  stanceBadgeClass,
  toneForSigned,
} from "@/components/display";
import {
  formatPct,
  formatQty,
  formatTs,
  formatUsd,
} from "@/components/format";
import { HypothesisTable } from "@/components/hypothesis-table";
import { FundEmpty, Panel, ProgressBar } from "@/components/panel";
import { PerformanceChart } from "@/components/performance-chart";
import { StatCard } from "@/components/stat-card";
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
  buildPerformanceHistory,
  extractFillsFromCycles,
  fundGrowth,
  getDefaultFund,
  getLatestState,
  latestHypothesesByInstrument,
  listCycles,
  normalizeSeriesTo100,
  summaryMetrics,
} from "@/lib/fund";
import type { Position } from "@/lib/types";
import { cn } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const fund = getDefaultFund();

  if (!fund) {
    return <FundEmpty />;
  }

  const cycles = listCycles(fund.fund_id);
  const state = getLatestState(fund.fund_id);
  const navSeries = buildNavSeries(fund, cycles);
  const fundSeries = normalizeSeriesTo100(navSeries);
  const trades = extractFillsFromCycles(cycles);
  const positions = openPositions(state?.positions ?? []);
  const history = buildPerformanceHistory(
    fund,
    cycles,
    state ?? {
      fund_id: fund.fund_id,
      as_of: fund.created_at,
      cash: fund.initial_cash,
      positions: [],
      nav: fund.initial_cash,
      peak_nav: fund.initial_cash,
      drawdown: "0",
      gross_exposure: "0",
      net_exposure: "0",
      short_exposure: "0",
      realized_pnl_cumulative: "0",
      cycle_count: 0,
      last_cycle_key: null,
    },
  );
  const growth = fundGrowth(fund, state?.nav ?? fund.initial_cash);
  const hypotheses = latestHypothesesByInstrument(cycles);
  const latestCycle = cycles[cycles.length - 1] ?? null;
  const openHypotheses = positions
    .map((p) => hypotheses.get(p.instrument_id))
    .filter((h): h is NonNullable<typeof h> => Boolean(h));

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
    grossExposure: state?.gross_exposure,
    netExposure: state?.net_exposure,
    shortExposure: state?.short_exposure,
    realizedPnl: state?.realized_pnl_cumulative,
    fillCount: trades.length,
    tradeCycleCount: history.tradeCount,
    holdCycleCount: history.holdCount,
    cycleCount: cycles.length,
  });

  const asOf = state?.as_of ?? endAsOf;
  const returnTone = toneForSigned(metrics.totalReturnPct);
  const pnlTone = toneForSigned(metrics.profitAndLoss);
  const drawdownTone = metrics.drawdown > 0 ? "negative" : "neutral";
  const recentCycles = [...cycles].reverse().slice(0, 6);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <header className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate font-mono text-base font-medium tracking-tight text-foreground tabular-nums">
              {fund.fund_id}
            </h2>
            <Badge variant="outline" className="font-mono text-[10px]">
              paper
            </Badge>
            <Badge variant="outline" className="font-mono text-[10px] capitalize">
              {history.status}
            </Badge>
            <Badge variant="outline" className="font-mono text-[10px] capitalize">
              {growth.stage}
            </Badge>
          </div>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Paper fund · $1,000 bankroll · $100k / 10y research objective
          </p>
        </div>
        <p className="font-mono text-xs text-muted-foreground tabular-nums">
          as of {formatTs(asOf)}
          {state?.last_cycle_key ? ` · ${state.last_cycle_key}` : ""}
        </p>
      </header>

      <section
        aria-label="Fund metrics"
        className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8"
      >
        <StatCard
          label="NAV"
          value={formatUsd(metrics.currentNav)}
          hint="Mark-to-market"
        />
        <StatCard
          label="P&L"
          value={formatUsd(metrics.profitAndLoss, { signed: true })}
          deltaTone={pnlTone}
          hint="Vs $1,000"
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
          hint={`Peak ${formatUsd(metrics.peakNav)}`}
        />
        <StatCard
          label="Cash"
          value={formatUsd(metrics.cash)}
          hint={`${formatPct(metrics.currentNav > 0 ? metrics.cash / metrics.currentNav : 1)} of NAV`}
        />
        <StatCard
          label="Gross / net"
          value={formatUsd(metrics.grossExposure)}
          hint={`Net ${formatUsd(metrics.netExposure, { signed: true })}`}
        />
        <StatCard
          label="Open positions"
          value={String(metrics.positionCount)}
          hint={`Short ${formatUsd(metrics.shortExposure)}`}
        />
        <StatCard
          label="Cycles"
          value={String(metrics.cycleCount)}
          hint={`${metrics.tradeCycleCount} trade · ${metrics.holdCycleCount} hold · ${metrics.fillCount} fills`}
        />
      </section>

      <div className="grid gap-3 lg:grid-cols-3">
        <Panel
          micro="Objective"
          title="Growth to $100k"
          trailing={growth.stage}
          className="lg:col-span-1"
          bodyClassName="flex flex-col gap-3 px-3.5 py-3"
        >
          <div className="flex items-end justify-between gap-3">
            <div>
              <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                Simple progress
              </p>
              <p className="font-mono text-lg tabular-nums">
                {formatPct(growth.simpleProgress)}
              </p>
            </div>
            <p className="font-mono text-xs text-muted-foreground tabular-nums">
              {growth.remainingMultiple.toFixed(1)}× remaining
            </p>
          </div>
          <ProgressBar value={growth.simpleProgress} />
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 font-mono text-xs tabular-nums">
            <dt className="text-muted-foreground">Log progress</dt>
            <dd className="text-right">{formatPct(growth.logProgress)}</dd>
            <dt className="text-muted-foreground">Required CAGR</dt>
            <dd className="text-right">
              {formatPct(growth.requiredAnnualReturn)}
            </dd>
            <dt className="text-muted-foreground">Realized P&L</dt>
            <dd className={cn("text-right", pnlClass(metrics.realizedPnl))}>
              {formatUsd(metrics.realizedPnl, { signed: true })}
            </dd>
            <dt className="text-muted-foreground">Up / down cycles</dt>
            <dd className="text-right">
              {history.positiveCycleCount} / {history.negativeCycleCount}
            </dd>
          </dl>
          {history.status === "measuring" ? (
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              {history.interpretation}
            </p>
          ) : null}
        </Panel>

        <Panel
          micro="Latest"
          title="Decision"
          trailing={
            latestCycle ? (
              <Link
                href={cycleHref(latestCycle.cycle_key)}
                className="text-foreground hover:underline"
              >
                {latestCycle.cycle_key}
              </Link>
            ) : (
              "—"
            )
          }
          className="lg:col-span-2"
          bodyClassName="flex flex-col gap-3 px-3.5 py-3"
        >
          {latestCycle ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge
                  variant="outline"
                  className={cn(
                    "font-mono text-[10px] capitalize",
                    actionBadgeClass(latestCycle.action),
                  )}
                >
                  {latestCycle.action}
                </Badge>
                <span className="font-mono text-xs text-muted-foreground tabular-nums">
                  {formatTs(latestCycle.as_of)}
                </span>
                <span className="font-mono text-xs tabular-nums">
                  NAV {formatUsd(latestCycle.state.nav)}
                </span>
              </div>
              <p className="text-sm leading-relaxed text-foreground">
                {latestCycle.thesis || "No thesis recorded."}
              </p>
              {latestCycle.journal ? (
                <dl className="grid gap-2 text-xs sm:grid-cols-2">
                  <div>
                    <dt className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                      What changed
                    </dt>
                    <dd className="mt-0.5 line-clamp-3 text-muted-foreground">
                      {latestCycle.journal.what_changed}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                      Portfolio intent
                    </dt>
                    <dd className="mt-0.5 line-clamp-3 text-muted-foreground">
                      {latestCycle.journal.portfolio_intent}
                    </dd>
                  </div>
                </dl>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Historical cycle — no journal sidecar.
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              Capitalized but no cycles applied yet.
            </p>
          )}
        </Panel>
      </div>

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

      <Panel
        micro="Holdings"
        title="Current positions"
        trailing={`${positions.length} open`}
      >
        {positions.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-muted-foreground">
            No open positions — cash only.
          </p>
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
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Stance
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
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Target
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Invalidation
                </TableHead>
                <TableHead className="pr-3.5 text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Unrealized
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.map((p: Position) => {
                const upnl = num(p.unrealized_pnl);
                const hyp = hypotheses.get(p.instrument_id);
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
                    <TableCell>
                      {hyp ? (
                        <Badge
                          variant="outline"
                          className={cn(
                            "font-mono text-[10px] capitalize",
                            stanceBadgeClass(hyp.stance),
                          )}
                        >
                          {hyp.stance}
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
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
                    <TableCell className="text-right font-mono text-sm tabular-nums">
                      {hyp?.target_price != null
                        ? formatUsd(hyp.target_price)
                        : "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm tabular-nums">
                      {hyp?.invalidation_price != null
                        ? formatUsd(hyp.invalidation_price)
                        : "—"}
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
      </Panel>

      {openHypotheses.length > 0 ? (
        <Panel
          micro="Theses"
          title="Open hypotheses"
          trailing={`${openHypotheses.length}`}
        >
          <HypothesisTable hypotheses={openHypotheses} />
        </Panel>
      ) : null}

      <Panel
        micro="Tape"
        title="Recent cycles"
        trailing={
          <Link href="/cycles" className="hover:text-foreground hover:underline">
            all cycles
          </Link>
        }
      >
        {recentCycles.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-muted-foreground">
            No cycles recorded yet.
          </p>
        ) : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-3.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  as_of
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  cycle_key
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  action
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  thesis
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  nav
                </TableHead>
                <TableHead className="pr-3.5 text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  fills
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recentCycles.map((c) => (
                <TableRow key={c.cycle_key}>
                  <TableCell className="pl-3.5 font-mono tabular-nums text-muted-foreground">
                    {formatTs(c.as_of)}
                  </TableCell>
                  <TableCell className="font-mono">
                    <Link
                      href={cycleHref(c.cycle_key)}
                      className="hover:underline"
                    >
                      {c.cycle_key}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className={cn(
                        "font-mono text-[10px] capitalize",
                        actionBadgeClass(c.action),
                      )}
                    >
                      {c.action}
                    </Badge>
                  </TableCell>
                  <TableCell className="max-w-[28rem] truncate text-muted-foreground">
                    {c.thesis}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatUsd(c.state.nav)}
                  </TableCell>
                  <TableCell className="pr-3.5 text-right font-mono tabular-nums">
                    {c.fills.length + c.settlements.length}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Panel>
    </div>
  );
}
