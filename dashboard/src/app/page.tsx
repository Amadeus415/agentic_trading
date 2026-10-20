import Link from "next/link";

import {
  actionLabel,
  contractName,
  contractOutcome,
  contractTitles,
  cycleHref,
  num,
  openPositions,
  pnlClass,
} from "@/components/display";
import { formatDay, formatPct, formatPrice, formatQty, formatTs, formatUsd } from "@/components/format";
import { Fact, Facts, FundEmpty, Money, Page, Quiet, Section } from "@/components/panel";
import { PerformanceChart } from "@/components/performance-chart";
import { fetchSpyBenchmarkSeries } from "@/lib/benchmark";
import {
  buildNavSeries,
  getLatestState,
  getSelectedFund,
  listCycles,
  listEvents,
  normalizeSeriesTo100,
  type FundSearchParams,
} from "@/lib/fund";
import type { Position } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function movement(ratio: number): string {
  const size = formatPct(Math.abs(ratio));
  if (size === "0%") return "flat";
  return ratio > 0 ? `up ${size}` : `down ${size}`;
}

function holdingDetail(p: Position): string {
  const outcome = contractOutcome(p.instrument_id);
  const qty = num(p.quantity);
  const entry = formatPrice(p.average_entry, p.asset_class);
  const mark = formatPrice(p.mark_price, p.asset_class);
  if (outcome) return `${formatQty(qty)} ${outcome} at ${entry}, now ${mark}`;
  const shares = `${formatQty(Math.abs(qty))} ${Math.abs(qty) === 1 ? "share" : "shares"}`;
  return `${qty < 0 ? "Short" : "Long"} ${shares} at ${entry}, now ${mark}`;
}

export default async function OverviewPage({ searchParams }: { searchParams: FundSearchParams }) {
  const fund = await getSelectedFund(searchParams);
  if (!fund) return <FundEmpty />;

  const cycles = listCycles(fund.fund_id);
  const state = getLatestState(fund.fund_id);
  const navSeries = buildNavSeries(fund, cycles);
  const fundSeries = normalizeSeriesTo100(navSeries);
  const positions = openPositions(state?.positions ?? []);
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
  const latest = cycles.at(-1) ?? null;
  const recent = [...cycles].reverse().slice(1, 6);
  const invested = positions.reduce((sum, p) => sum + Math.abs(num(p.market_value)), 0);

  return (
    <Page>
      <section className="flex flex-col gap-10">
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

        <Facts>
          <Fact label="Cash">{formatUsd(state?.cash ?? fund.initial_cash)}</Fact>
          <Fact label="Invested">{formatUsd(invested)}</Fact>
          <Fact label="Gain or loss">
            <Money value={nav - initial} />
          </Fact>
          <Fact label="Below peak">{formatPct(num(state?.drawdown))}</Fact>
        </Facts>
      </section>

      <Section title="Open positions" aside={positions.length ? `${positions.length} open` : null}>
        {positions.length === 0 ? (
          <Quiet>All in cash.</Quiet>
        ) : (
          <ul className="flex flex-col">
            {positions.map((p) => (
              <li key={p.instrument_id} className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-0.5 border-t py-4">
                <span className="min-w-0">{contractName(titles, p.instrument_id, p.asset_class)}</span>
                <Money value={p.unrealized_pnl} />
                <span className="text-sm text-graphite">{holdingDetail(p)}</span>
                <span className="text-right text-sm text-graphite">{formatUsd(p.market_value)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {latest ? (
        <Section
          title="Latest decision"
          aside={`${actionLabel(latest.action)}, ${formatTs(latest.as_of)}`}
        >
          <div className="flex flex-col gap-5 border-t pt-6">
            <p className="max-w-[68ch] text-[17px] leading-[1.7] font-light">{latest.thesis || "No reasoning recorded."}</p>
            <Link href={cycleHref(latest.cycle_key, fund.fund_id)} className="self-start text-sm text-fund hover:underline">
              Read the full reasoning
            </Link>
          </div>
        </Section>
      ) : (
        <Section title="Latest decision">
          <Quiet>No decisions yet. The first research session will add one.</Quiet>
        </Section>
      )}

      {recent.length > 0 ? (
        <Section
          title="Earlier decisions"
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
