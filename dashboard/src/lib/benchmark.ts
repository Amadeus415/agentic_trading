/**
 * SPY (S&P 500 proxy) daily closes from Yahoo Finance chart API.
 * Completed daily price closes only; dividends are excluded. Failure returns null.
 */
import type { PerformancePoint } from "./types";

const YAHOO_CHART =
  "https://query1.finance.yahoo.com/v8/finance/chart/SPY";

const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

type CacheEntry = {
  expiresAt: number;
  series: PerformancePoint[] | null;
};

const cache = new Map<string, CacheEntry>();

function toUnixSeconds(isoOrMs: string | number): number {
  if (typeof isoOrMs === "number") {
    return isoOrMs > 1e12 ? Math.floor(isoOrMs / 1000) : Math.floor(isoOrMs);
  }
  const ms = Date.parse(isoOrMs);
  if (!Number.isFinite(ms)) {
    return Math.floor(Date.now() / 1000);
  }
  return Math.floor(ms / 1000);
}

function cacheKey(period1: number, period2: number): string {
  // Bucket period2 to 5-minute windows so concurrent requests share cache.
  const bucket = Math.floor(period2 / 300) * 300;
  return `SPY:${period1}:${bucket}`;
}

type YahooChartResult = {
  chart?: {
    result?: Array<{
      timestamp?: number[];
      indicators?: {
        quote?: Array<{
          close?: Array<number | null>;
        }>;
      };
    }>;
    error?: unknown;
  };
};

async function fetchSpyCloses(
  period1: number,
  period2: number,
): Promise<Array<{ as_of: string; close: number }> | null> {
  const url = `${YAHOO_CHART}?interval=1d&period1=${period1}&period2=${period2}`;
  try {
    const res = await fetch(url, {
      headers: {
        // Yahoo occasionally rejects bare fetches without a UA.
        "User-Agent": "EdgecraftDashboard/1.0",
        Accept: "application/json",
      },
      // Avoid Next fetch caching surprises for live market data.
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) {
      return null;
    }
    const body = (await res.json()) as YahooChartResult;
    const result = body.chart?.result?.[0];
    if (!result?.timestamp?.length) {
      return null;
    }
    const closes = result.indicators?.quote?.[0]?.close ?? [];
    const out: Array<{ as_of: string; close: number }> = [];
    for (let i = 0; i < result.timestamp.length; i++) {
      const ts = result.timestamp[i];
      const close = closes[i];
      if (close == null || !Number.isFinite(close)) continue;
      out.push({
        // Yahoo daily bar timestamps denote the session start. Use 21:00 UTC
        // as a conservative availability cutoff (16:00 ET or one hour later).
        as_of: new Date(new Date(ts * 1000).setUTCHours(21, 0, 0, 0)).toISOString(),
        close,
      });
    }
    return out.length > 0 ? out : null;
  } catch {
    return null;
  }
}

/** Normalize against the last completed close known at inception, never a future close. */
export function alignBenchmark(
  closes: Array<{ as_of: string; close: number }>,
  startAsOf: string,
  endAsOf: string,
): PerformancePoint[] | null {
  const start = Date.parse(startAsOf);
  const end = Date.parse(endAsOf);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  const rows = closes.filter(row => Number.isFinite(row.close) && row.close > 0 &&
    Number.isFinite(Date.parse(row.as_of)) && Date.parse(row.as_of) <= end)
    .sort((a, b) => Date.parse(a.as_of) - Date.parse(b.as_of));
  const base = rows.filter(row => Date.parse(row.as_of) <= start).at(-1);
  if (!base) return null;
  return [
    { as_of: startAsOf, value: 100, nav: base.close },
    ...rows.filter(row => Date.parse(row.as_of) > start).map(row => ({
      as_of: row.as_of, value: row.close / base.close * 100, nav: row.close,
    })),
  ];
}

/** Price-return proxy over the fund observation window, with no look-ahead. */
export async function fetchSpyBenchmarkSeries(
  startAsOf: string,
  endAsOf: string = new Date().toISOString(),
): Promise<PerformancePoint[] | null> {
  const start = Date.parse(startAsOf);
  const end = Math.min(Date.parse(endAsOf), Date.now());
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  const period1 = toUnixSeconds(startAsOf);
  const period2 = Math.floor(end / 1000);
  const key = `${cacheKey(period1, period2)}:${end}`;
  const hit = cache.get(key);
  if (hit && hit.expiresAt > Date.now()) return hit.series;
  const closes = await fetchSpyCloses(Math.max(0, period1 - 7 * 86400), period2 + 1);
  const series = closes ? alignBenchmark(closes, startAsOf, new Date(end).toISOString()) : null;
  if (cache.size > 100) cache.clear();
  cache.set(key, { expiresAt: Date.now() + CACHE_TTL_MS, series });
  return series;
}
