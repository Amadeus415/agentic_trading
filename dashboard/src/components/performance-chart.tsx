"use client";

import * as React from "react";
import {
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { PerformancePoint } from "@/lib/types";
import { formatDay, formatPct, formatTs } from "@/components/format";

// Mirrors the tokens in globals.css; SVG attributes need literal colors.
const FUND = "#2344e0";
const SPY = "#a3a8b1";
const LINE = "#e6e8ec";
const MIST = "#a3a8b1";

export type PerformanceChartProps = {
  fundSeries: PerformancePoint[];
  /** Null/empty when benchmark fetch failed — fund-only mode. */
  benchmarkSeries?: PerformancePoint[] | null;
  height?: number;
};

type ChartRow = { t: number; fund: number | null; benchmark: number | null };

function toMs(asOf: string): number {
  const ms = Date.parse(asOf);
  return Number.isFinite(ms) ? ms : 0;
}

/**
 * Merge fund + benchmark onto one time axis as percent returns.
 * Forward-fills each series so both lines stay continuous across sparse points.
 */
function buildChartData(
  fundSeries: PerformancePoint[],
  benchmarkSeries: PerformancePoint[] | null | undefined,
): ChartRow[] {
  const fundByT = new Map(fundSeries.map((p) => [toMs(p.as_of), p.value] as const));
  const benchByT = new Map((benchmarkSeries ?? []).map((p) => [toMs(p.as_of), p.value] as const));
  const times = [...new Set([...fundByT.keys(), ...benchByT.keys()])].filter((t) => t > 0).sort((a, b) => a - b);

  let lastFund: number | null = null;
  let lastBench: number | null = null;
  return times.map((t) => {
    if (fundByT.has(t)) lastFund = fundByT.get(t)! - 100;
    if (benchByT.has(t)) lastBench = benchByT.get(t)! - 100;
    return { t, fund: lastFund, benchmark: benchmarkSeries ? lastBench : null };
  });
}

function axisPct(value: number): string {
  if (!Number.isFinite(value)) return "";
  if (value === 0) return "0%";
  const size = Math.abs(value);
  return `${value > 0 ? "+" : "−"}${Number.isInteger(size) ? size : size.toFixed(1)}%`;
}

/** Round bounds and 3–5 evenly spaced ticks that always include 0%. */
function niceTicks(rows: ChartRow[]): number[] {
  const values = rows.flatMap((r) => [r.fund, r.benchmark]).filter((v): v is number => v != null);
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const span = Math.max(hi - lo, 1);
  const step = [0.5, 1, 2, 5, 10, 20, 50, 100].find((s) => span / s <= 4) ?? 200;
  const ticks: number[] = [];
  for (let t = Math.floor(lo / step) * step; t <= Math.ceil(hi / step) * step + 1e-9; t += step) ticks.push(Number(t.toFixed(4)));
  return ticks;
}

type TooltipItem = { dataKey?: string | number; value?: number | string | null };

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: TooltipItem[]; label?: number }) {
  if (!active || !payload?.length || label == null) return null;
  const value = (key: string) => payload.find((item) => item.dataKey === key)?.value;
  const fund = value("fund");
  const benchmark = value("benchmark");
  return (
    <div className="rounded-lg border bg-paper px-3.5 py-2.5 text-[13px] shadow-[0_8px_24px_-12px_rgb(21_23_28/0.18)]">
      <p className="mb-1.5 text-graphite">{formatTs(label)}</p>
      {fund != null ? (
        <p className="flex justify-between gap-8">
          <span>Fund</span>
          <span>{formatPct(Number(fund), { alreadyPercent: true, signed: true })}</span>
        </p>
      ) : null}
      {benchmark != null ? (
        <p className="flex justify-between gap-8 text-graphite">
          <span>S&amp;P 500</span>
          <span>{formatPct(Number(benchmark), { alreadyPercent: true, signed: true })}</span>
        </p>
      ) : null}
    </div>
  );
}

/** Fund (ink blue) against the S&P 500 (mist, dashed), both as return since inception. */
export function PerformanceChart({ fundSeries, benchmarkSeries, height = 280 }: PerformanceChartProps) {
  const data = React.useMemo(() => buildChartData(fundSeries, benchmarkSeries), [fundSeries, benchmarkSeries]);
  const hasBenchmark = data.some((d) => d.benchmark != null);

  if (data.length === 0) {
    return (
      <div className="flex items-center text-graphite" style={{ height }}>
        The chart starts after the first decision.
      </div>
    );
  }

  const ticks = niceTicks(data);
  const tick = { fill: MIST, fontSize: 12, fontFamily: "var(--font-sans)" };

  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 0, left: 0, bottom: 0 }}>
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(t: number) => formatDay(t)}
            tick={tick}
            tickLine={false}
            axisLine={{ stroke: LINE }}
            minTickGap={64}
            dy={8}
          />
          <YAxis
            orientation="right"
            domain={[ticks[0], ticks.at(-1)!]}
            ticks={ticks}
            tickFormatter={axisPct}
            tick={tick}
            tickLine={false}
            axisLine={false}
            width={48}
          />
          <ReferenceLine y={0} stroke={LINE} />
          <Tooltip content={<ChartTooltip />} cursor={{ stroke: LINE, strokeWidth: 1 }} />
          {hasBenchmark ? (
            <Line
              type="stepAfter"
              dataKey="benchmark"
              stroke={SPY}
              strokeWidth={1}
              strokeDasharray="3 3"
              dot={false}
              activeDot={{ r: 2.5, fill: SPY, strokeWidth: 0 }}
              isAnimationActive={false}
              connectNulls
            />
          ) : null}
          <Line
            type="stepAfter"
            dataKey="fund"
            stroke={FUND}
            strokeWidth={1.5}
            dot={data.length <= 3 ? { r: 2, fill: FUND, strokeWidth: 0 } : false}
            activeDot={{ r: 3, fill: FUND, strokeWidth: 0 }}
            isAnimationActive={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
