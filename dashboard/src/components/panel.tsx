import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Panel({
  micro,
  title,
  trailing,
  children,
  className,
  bodyClassName,
}: {
  micro: string;
  title: string;
  trailing?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={cn(
        "flex flex-col rounded-lg border border-border bg-card",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-border px-3.5 py-2.5">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
            {micro}
          </span>
          <h2 className="truncate text-sm font-medium text-foreground">
            {title}
          </h2>
        </div>
        {trailing ? (
          <div className="shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
            {trailing}
          </div>
        ) : null}
      </div>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function ProgressBar({
  value,
  className,
}: {
  value: number;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(100, value * 100));
  return (
    <div
      className={cn(
        "h-1.5 w-full overflow-hidden rounded-full bg-muted",
        className,
      )}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
    >
      <div
        className="h-full rounded-full bg-primary"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function FundEmpty({
  title = "No funds found",
  detail = "Initialize the paper fund ledger, then refresh this page.",
}: {
  title?: string;
  detail?: string;
}) {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <section className="rounded-lg border border-border bg-card px-4 py-10 text-center">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
      </section>
    </div>
  );
}
