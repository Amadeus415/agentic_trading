/**
 * SPY (S&P 500 proxy) daily closes from Yahoo Finance chart API.
 * Normalized to 100 at the fund start timestamp; failure returns null.
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
        as_of: new Date(ts * 1000).toISOString(),
        close,
      });
    }
    return out.length > 0 ? out : null;
  } catch {
    return null;
  }
}

/**
 * Fetch SPY daily closes aligned to [startAsOf, endAsOf], normalized to 100
 * at the first usable close on/after the fund start. Returns null on failure.
 */
export async function fetchSpyBenchmarkSeries(
  startAsOf: string,
  endAsOf?: string,
): Promise<PerformancePoint[] | null> {
  const period1 = toUnixSeconds(startAsOf);
  // Yahoo period2 is exclusive-ish; pad a day so "today" is included.
  const endMs = endAsOf ? Date.parse(endAsOf) : Date.now();
  const period2 = Math.floor((Number.isFinite(endMs) ? endMs : Date.now()) / 1000) + 86_400;

  // Start a few days early so we have a close at/before fund inception.
  const fetchStart = Math.max(0, period1 - 7 * 86_400);

  const key = cacheKey(period1, period2);
  const hit = cache.get(key);
  if (hit && hit.expiresAt > Date.now()) {
    return hit.series;
  }

  const closes = await fetchSpyCloses(fetchStart, period2);
  if (!closes || closes.length === 0) {
    cache.set(key, { expiresAt: Date.now() + CACHE_TTL_MS, series: null });
    return null;
  }

  // Base = first close on or after fund start; fall back to last close before start.
  let baseClose: number | null = null;
  for (const row of closes) {
    if (toUnixSeconds(row.as_of) >= period1) {
      baseClose = row.close;
      break;
    }
  }
  if (baseClose == null) {
    // Use the last available close before start as base.
    for (let i = closes.length - 1; i >= 0; i--) {
      if (toUnixSeconds(closes[i].as_of) <= period1) {
        baseClose = closes[i].close;
        break;
      }
    }
  }
  if (baseClose == null || baseClose === 0) {
    cache.set(key, { expiresAt: Date.now() + CACHE_TTL_MS, series: null });
    return null;
  }

  const series: PerformancePoint[] = [];
  for (const row of closes) {
    const t = toUnixSeconds(row.as_of);
    if (t < period1) continue;
    if (t > period2) continue;
    series.push({
      as_of: row.as_of,
      value: (row.close / baseClose) * 100,
      nav: row.close,
    });
  }

  // Ensure a point at fund start if the first daily bar is later.
  if (series.length === 0) {
    // No bars in range — still emit base at start for UI alignment.
    series.push({
      as_of: startAsOf,
      value: 100,
      nav: baseClose,
    });
  } else if (toUnixSeconds(series[0].as_of) > period1) {
    series.unshift({
      as_of: startAsOf,
      value: 100,
      nav: baseClose,
    });
  } else {
    // Force first aligned point to exactly 100.
    series[0] = { ...series[0], value: 100 };
  }

  cache.set(key, { expiresAt: Date.now() + CACHE_TTL_MS, series });
  return series;
}

/** Test helper: clear in-memory cache. */
export function clearBenchmarkCache(): void {
  cache.clear();
}
