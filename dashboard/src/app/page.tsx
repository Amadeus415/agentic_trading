import Link from "next/link";

import {
  actionLabel,
  contractName,
  contractOutcome,
  contractTitles,
  cycleHref,
  holdingDetail,
  num,
  openPositions,
  pnlClass,
  positionHref,
} from "@/components/display";
import { formatDay, formatPct, formatUsd } from "@/components/format";
import { Fact, Facts, FundEmpty, Money, Page, Quiet, Section } from "@/components/panel";
import { PerformanceChart } from "@/components/performance-chart";
import { fetchSpyBenchmarkSeries } from "@/lib/benchmark";
import {
  buildNavSeries,
  closedPositions,
  extractFillsFromCycles,
  getLatestState,
  getSelectedFund,
  listCycles,
  listEvents,
  normalizeSeriesTo100,
  type FundSearchParams,
} from "@/lib/fund";
import type { ClosedPosition } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function movement(ratio: number): string {
  const size = formatPct(Math.abs(ratio));
  if (size === "0%") return "flat";
  return ratio > 0 ? `up ${size}` : `down ${size}`;
}

function closedDetail(c: ClosedPosition): string {
  const outcome = contractOutcome(c.instrument_id);
  const trades = `${c.trade_count} ${c.trade_count === 1 ? "trade" : "trades"}`;
  return `${outcome ? `${outcome}, ` : ""}${trades}, closed ${formatDay(c.closed_at)}`;
}

const ROW = "-mx-3 grid grid-cols-[1fr_auto] gap-x-6 gap-y-0.5 rounded-md px-3 py-4 hover:bg-wash";

export default async function OverviewPage({ searchParams }: { searchParams: FundSearchParams }) {
  const fund = await getSelectedFund(searchParams);
  if (!fund) return <FundEmpty />;

  const cycles = listCycles(fund.fund_id);
  const state = getLatestState(fund.fund_id);
  const navSeries = buildNavSeries(fund, cycles);
  const fundSeries = normalizeSeriesTo100(navSeries);
  const positions = openPositions(state?.positions ?? []);
  const closed = closedPositions(extractFillsFromCycles(cycles), positions);
  const titles = contractTitles(cycles);
  const retired = listEvents(fund.fund_id).some((event) => event.event_type === "fund_retired");

  const startAsOf = navSeries[0]?.as_of ?? fund.created_at;
  const endAsOf = navSeries.at(-1)?.as_of ?? state?.as_of ?? new Date().toISOString();
  let benchmarkSeries: Awaited<ReturnType<typeof fetchSpyBenchmarkSeries>> = null;
  try {
    benchmarkSeries = await fetchSpyBenchmarkSeries(startAsOf, endAsOf);
    if (!benchmarkSeries?.length) benchmarkSeries = null;
  } catch {
    benchmarkSeries = null;
  }

  const initial = num(fund.initial_cash);
  const nav = num(state?.nav ?? fund.initial_cash);
  const fundReturn = initial > 0 ? nav / initial - 1 : 0;
  const spyReturn = benchmarkSeries ? benchmarkSeries.at(-1)!.value / 100 - 1 : null;
  const [dollars, cents] = formatUsd(nav).split(".");
  const recent = [...cycles].reverse().slice(0, 5);
  const invested = positions.reduce((sum, p) => sum + Math.abs(num(p.market_value)), 0);

  return (
    <Page>
      <section className="flex flex-col gap-10">
        <div className="flex flex-col gap-3">
          <PerformanceChart fundSeries={fundSeries} benchmarkSeries={benchmarkSeries} />
          <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 text-[13px] text-mist">
            <div className="flex gap-5">
              <span className="flex items-center gap-2">
                <span aria-hidden className="h-px w-4 bg-fund" />
                Fund
              </span>
              <span className="flex items-center gap-2">
                <span aria-hidden className="w-4 border-t border-dashed border-mist" />
                S&amp;P 500
              </span>
            </div>
            <span>{spyReturn != null ? "SPY price return, no dividends" : "S&P 500 data unavailable"}</span>
          </div>
        </div>

        <div>
          <p className="text-[64px] leading-none font-extralight tracking-[-0.045em] [font-variant-numeric:proportional-nums] sm:text-[104px]">
            {dollars}
            <span className="text-mist">.{cents}</span>
          </p>
          <p className="mt-6 max-w-[46ch] text-[19px] leading-snug font-light text-graphite">
            <span className={pnlClass(fundReturn)}>{movement(fundReturn).replace(/^./, (c) => c.toUpperCase())}</span>{" "}
            since {formatDay(fund.created_at)}.
            {spyReturn != null ? ` The S&P 500 is ${movement(spyReturn)} over the same stretch.` : null}
            {retired ? " This fund is retired." : null}
          </p>
        </div>

        <Facts>
          <Fact label="Cash">{formatUsd(state?.cash ?? fund.initial_cash)}</Fact>
          <Fact label="Invested">{formatUsd(invested)}</Fact>
          <Fact label="Gain or loss">
            <Money value={nav - initial} />
          </Fact>
          <Fact label="Below peak">{formatPct(num(state?.drawdown))}</Fact>
        </Facts>
      </section>

      <Section
        title="Positions"
        aside={positions.length || closed.length ? `${positions.length} open, ${closed.length} closed` : null}
      >
        {positions.length === 0 ? (
          <Quiet>All in cash.</Quiet>
        ) : (
          <ul className="flex flex-col">
            {positions.map((p) => (
              <li key={p.instrument_id} className="border-t">
                <Link href={positionHref(p.instrument_id, fund.fund_id)} className={ROW}>
                  <span className="min-w-0">{contractName(titles, p.instrument_id, p.asset_class)}</span>
                  <Money value={p.unrealized_pnl} />
                  <span className="text-sm text-graphite">{holdingDetail(p)}</span>
                  <span className="text-right text-sm text-graphite">{formatUsd(p.market_value)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}

        {closed.length > 0 ? (
          <div className="mt-6 flex flex-col gap-3">
            <h3 className="text-[13px] text-graphite">Closed</h3>
            <ul className="flex flex-col">
              {closed.map((c) => (
                <li key={c.instrument_id} className="border-t">
                  <Link href={positionHref(c.instrument_id, fund.fund_id)} className={ROW}>
                    <span className="min-w-0">{contractName(titles, c.instrument_id, c.asset_class)}</span>
                    <Money value={c.result} />
                    <span className="col-span-2 text-sm text-graphite">{closedDetail(c)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Section>

      {recent.length > 0 ? (
        <Section
          title="Recent decisions"
          aside={
            <Link href={`/cycles?fund=${encodeURIComponent(fund.fund_id)}`} className="hover:text-ink">
              See all {cycles.length}
            </Link>
          }
        >
          <ul className="flex flex-col">
            {recent.map((c) => (
              <li key={c.cycle_key} className="border-t">
                <Link
                  href={cycleHref(c.cycle_key, fund.fund_id)}
                  className="-mx-3 grid grid-cols-[4.5rem_1fr_auto] items-baseline gap-x-5 rounded-md px-3 py-3.5 hover:bg-wash sm:grid-cols-[4.5rem_4.5rem_1fr_auto]"
                >
                  <span className="text-sm text-graphite">{formatDay(c.as_of)}</span>
                  <span className="hidden text-sm text-graphite sm:block">{actionLabel(c.action)}</span>
                  <span className="truncate">{c.thesis}</span>
                  <span className="text-sm">{formatUsd(c.state.nav)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </Page>
  );
}
