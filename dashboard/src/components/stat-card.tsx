import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type StatDeltaTone = "positive" | "negative" | "neutral";

export interface StatCardProps {
  /** Muted upper label, e.g. "NAV" */
  label: string;
  /** Mono primary value already formatted (use formatUsd / formatPct) */
  value: ReactNode;
  /** Optional secondary change line */
  delta?: ReactNode;
  /** Color for delta; defaults to neutral */
  deltaTone?: StatDeltaTone;
  className?: string;
  /** Optional micro-hint under delta */
  hint?: string;
}

const deltaToneClass: Record<StatDeltaTone, string> = {
  positive: "text-success",
  negative: "text-danger",
  neutral: "text-muted-foreground",
};

/**
 * Compact metric tile for dashboard density (PostHog / Linear style).
 * No glassmorphism; hairline border + elevated surface only.
 */
export function StatCard({
  label,
  value,
  delta,
  deltaTone = "neutral",
  className,
  hint,
}: StatCardProps) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-1 rounded-lg border border-border bg-card px-3.5 py-3",
        className
      )}
    >
      <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </div>
      <div className="font-mono text-lg leading-none font-medium tracking-tight text-foreground tabular-nums">
        {value}
      </div>
      {delta != null && delta !== "" && (
        <div
          className={cn(
            "font-mono text-xs tabular-nums",
            deltaToneClass[deltaTone]
          )}
        >
          {delta}
        </div>
      )}
      {hint ? (
        <div className="text-[11px] text-muted-foreground/80">{hint}</div>
      ) : null}
    </div>
  );
}
