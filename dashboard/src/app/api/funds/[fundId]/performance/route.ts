import { NextResponse } from "next/server";
import { fetchSpyBenchmarkSeries } from "@/lib/benchmark";
import {
  buildNavSeries,
  extractFillsFromCycles,
  getFund,
  getLatestState,
  listCycles,
  normalizeSeriesTo100,
  summaryMetrics,
} from "@/lib/fund";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ fundId: string }>;
};

export async function GET(_request: Request, context: RouteContext) {
  try {
    const { fundId } = await context.params;
    const fund = getFund(fundId);
    if (!fund) {
      return NextResponse.json({ error: "Fund not found" }, { status: 404 });
    }

    const cycles = listCycles(fundId);
    const state = getLatestState(fundId);
    const navSeries = buildNavSeries(fund, cycles);
    const fundSeries = normalizeSeriesTo100(navSeries);
    const trades = extractFillsFromCycles(cycles);

    const startAsOf = navSeries[0]?.as_of ?? fund.created_at;
    const endAsOf =
      navSeries[navSeries.length - 1]?.as_of ?? new Date().toISOString();

    const benchmarkSeries = await fetchSpyBenchmarkSeries(startAsOf, endAsOf);

    const positions = state?.positions ?? [];
    const metrics = summaryMetrics(navSeries, positions, {
      cash: state?.cash,
      peakNav: state?.peak_nav,
      drawdown: state?.drawdown,
      tradeCount: trades.length,
    });

    return NextResponse.json({
      fundSeries,
      benchmarkSeries,
      metrics,
      positions,
    });
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Failed to load performance";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
