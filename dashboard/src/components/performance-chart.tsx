"use client";

import * as React from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { PerformancePoint } from "@/lib/types";
import { formatTs } from "@/components/format";
import { cn } from "@/lib/utils";

export type PerformanceChartProps = {
  fundSeries: PerformancePoint[];
  /** Null/empty when benchmark fetch failed — fund-only mode. */
  benchmarkSeries?: PerformancePoint[] | null;
  className?: string;
  height?: number;
};

type ChartRow = {
  t: number;
  as_of: string;
  fund: number | null;
  benchmark: number | null;
};

function toMs(asOf: string): number {
  const ms = Date.parse(asOf);
  return Number.isFinite(ms) ? ms : 0;
}

/**
 * Merge fund + benchmark series onto a shared time axis.
 * Forward-fills each series so dual lines stay continuous across sparse points.
 */
function buildChartData(
  fundSeries: PerformancePoint[],
  benchmarkSeries: PerformancePoint[] | null | undefined,
): ChartRow[] {
  const times = new Set<number>();
  for (const p of fundSeries) times.add(toMs(p.as_of));
  if (benchmarkSeries) {
    for (const p of benchmarkSeries) times.add(toMs(p.as_of));
  }

  const sorted = [...times].filter((t) => t > 0).sort((a, b) => a - b);
  if (sorted.length === 0) return [];

  // Ensure at least two x-points so a single NAV still draws a flat segment.
  if (sorted.length === 1) {
    sorted.push(sorted[0] + 86_400_000);
  }

  const fundByT = new Map(
    fundSeries.map((p) => [toMs(p.as_of), p.value] as const),
  );
  const benchByT = new Map(
    (benchmarkSeries ?? []).map((p) => [toMs(p.as_of), p.value] as const),
  );

  let lastFund: number | null = null;
  let lastBench: number | null = null;
  const rows: ChartRow[] = [];

  for (const t of sorted) {
    if (fundByT.has(t)) lastFund = fundByT.get(t) ?? null;
    if (benchByT.has(t)) lastBench = benchByT.get(t) ?? null;
    rows.push({
      t,
      as_of: new Date(t).toISOString(),
      fund: lastFund,
      benchmark: benchmarkSeries ? lastBench : null,
    });
  }

  // If fund only has one real observation, pin both ends to that value.
  if (fundSeries.length === 1 && rows.length >= 2) {
    const v = fundSeries[0].value;
    rows[0].fund = v;
    rows[rows.length - 1].fund = v;
    if (!rows[0].as_of || rows[0].t !== toMs(fundSeries[0].as_of)) {
      rows[0].as_of = fundSeries[0].as_of;
      rows[0].t = toMs(fundSeries[0].as_of);
    }
  }

  return rows;
}

function formatAxisDate(iso: string): string {
  return formatTs(iso, { dateOnly: true });
}

function formatAxisValue(v: number): string {
  if (!Number.isFinite(v)) return "";
  return v.toFixed(v >= 100 && v < 1000 ? 1 : 2);
}

type TooltipPayloadItem = {
  dataKey?: string | number;
  value?: number | string | null;
  color?: string;
  name?: string;
};

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;

  const asOf =
    (typeof label === "string" || typeof label === "number") && label !== ""
      ? String(label)
      : "";

  // Area + Line share dataKey "fund"; keep one fund row and skip the area fill.
  const seen = new Set<string>();
  const items: TooltipPayloadItem[] = [];
  for (const item of payload) {
    const key = String(item.dataKey ?? item.name ?? "");
    if (item.value == null) continue;
    if (item.name === "fundArea") continue;
    if (key === "fund" || key === "Edgecraft") {
      if (seen.has("fund")) continue;
      seen.add("fund");
      items.push(item);
      continue;
    }
    if (key === "benchmark" || key === "S&P 500") {
      if (seen.has("benchmark")) continue;
      seen.add("benchmark");
      items.push(item);
      continue;
    }
  }

  return (
    <div className="rounded-md border border-border bg-zinc-950/95 px-3 py-2 shadow-lg backdrop-blur-sm">
      <div className="mb-1.5 font-mono text-[10px] tracking-wide text-zinc-400 tabular-nums">
        {asOf ? formatTs(asOf) : "—"}
      </div>
      <div className="flex flex-col gap-1">
        {items.map((item) => {
          const key = String(item.dataKey ?? item.name ?? "");
          const name =
            key === "fund" || key === "Edgecraft"
              ? "Edgecraft"
              : key === "benchmark" || key === "S&P 500"
                ? "S&P 500"
                : key;
          const n =
            typeof item.value === "number"
              ? item.value
              : Number(item.value);
          return (
            <div
              key={name}
              className="flex items-center justify-between gap-6 font-mono text-xs tabular-nums"
            >
              <span className="flex items-center gap-1.5 text-zinc-300">
                <span
                  aria-hidden
                  className="inline-block size-1.5 rounded-full"
                  style={{
                    background:
                      name === "Edgecraft"
                        ? "#818cf8"
                        : (item.color ?? "#a1a1aa"),
                  }}
                />
                {name}
              </span>
              <span className="text-zinc-100">
                {Number.isFinite(n) ? n.toFixed(2) : "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Dual-line performance chart: Edgecraft (indigo) vs S&P 500 / SPY (zinc).
 * Both series are expected pre-normalized to 100 at fund inception.
 */
export function PerformanceChart({
  fundSeries,
  benchmarkSeries,
  className,
  height = 360,
}: PerformanceChartProps) {
  const data = React.useMemo(
    () => buildChartData(fundSeries, benchmarkSeries),
    [fundSeries, benchmarkSeries],
  );

  const hasBenchmark =
    Boolean(benchmarkSeries?.length) &&
    data.some((d) => d.benchmark != null);

  if (data.length === 0) {
    return (
      <div
        className={cn(
          "flex items-center justify-center text-sm text-muted-foreground",
          className,
        )}
        style={{ height }}
      >
        No performance data yet.
      </div>
    );
  }

  return (
    <div className={cn("w-full", className)} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={data}
          margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
        >
          <defs>
            <linearGradient id="fundAreaFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6366f1" stopOpacity={0.18} />
              <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid
            stroke="rgb(63 63 70 / 35%)"
            strokeDasharray="3 4"
            vertical={false}
          />
          <XAxis
            dataKey="as_of"
            tickFormatter={formatAxisDate}
            tick={{
              fill: "#71717a",
              fontSize: 11,
              fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
            }}
            tickLine={false}
            axisLine={{ stroke: "rgb(63 63 70 / 50%)" }}
            minTickGap={48}
            dy={6}
          />
          <YAxis
            domain={["auto", "auto"]}
            tickFormatter={formatAxisValue}
            tick={{
              fill: "#71717a",
              fontSize: 11,
              fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
            }}
            tickLine={false}
            axisLine={false}
            width={48}
            dx={-4}
          />
          <Tooltip
            content={<ChartTooltip />}
            cursor={{ stroke: "rgb(113 113 122 / 40%)", strokeWidth: 1 }}
            // label is as_of string from dataKey
            labelFormatter={(label) => String(label)}
          />
          <Area
            type="monotone"
            dataKey="fund"
            name="fundArea"
            stroke="none"
            fill="url(#fundAreaFill)"
            isAnimationActive={false}
            connectNulls
            legendType="none"
            tooltipType="none"
          />
          {hasBenchmark ? (
            <Line
              type="monotone"
              dataKey="benchmark"
              name="S&P 500"
              stroke="#71717a"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
              connectNulls
              activeDot={{ r: 3, fill: "#a1a1aa", strokeWidth: 0 }}
            />
          ) : null}
          <Line
            type="monotone"
            dataKey="fund"
            name="Edgecraft"
            stroke="#818cf8"
            strokeWidth={2}
            dot={data.length <= 3}
            isAnimationActive={false}
            connectNulls
            activeDot={{ r: 4, fill: "#a5b4fc", strokeWidth: 0 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
