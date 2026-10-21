import type { ReactNode } from "react";

import { pnlClass } from "@/components/display";
import { formatUsd } from "@/components/format";
import { cn } from "@/lib/utils";

export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("flex flex-col gap-16 pb-8", className)}>{children}</div>;
}

export function PageTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
      <h1 className="text-[32px] leading-tight font-light tracking-[-0.02em]">{children}</h1>
      {aside ? <p className="text-sm text-graphite">{aside}</p> : null}
    </header>
  );
}

export function Section({
  title,
  aside,
  children,
  className,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("flex flex-col gap-5", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 className="text-[17px] font-medium tracking-[-0.01em]">{title}</h2>
        {aside ? <div className="text-sm text-graphite">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

/** A quiet label over a value, laid out in a row of facts. */
export function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-[13px] text-graphite">{label}</dt>
      <dd className="text-xl font-light tracking-[-0.01em]">{children}</dd>
    </div>
  );
}

export function Facts({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-2 gap-x-8 gap-y-6 border-t pt-6 sm:grid-cols-4", className)}>
      {children}
    </dl>
  );
}

export function Money({ value, signed = true }: { value: number | string | null | undefined; signed?: boolean }) {
  return <span className={pnlClass(Number(value ?? 0))}>{formatUsd(value, { signed })}</span>;
}

/** Wide tables scroll sideways on phones instead of squeezing. */
export function TableWrap({ children }: { children: ReactNode }) {
  return <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">{children}</div>;
}

/** A labeled paragraph in a definition list; renders nothing when empty. */
export function Note({ label, children }: { label: string; children: ReactNode }) {
  if (!children || (Array.isArray(children) && children.length === 0)) return null;
  return (
    <div className="grid gap-1 border-t py-5 sm:grid-cols-[11rem_1fr] sm:gap-8">
      <dt className="text-sm text-graphite">{label}</dt>
      <dd className="max-w-[68ch] leading-[1.7]">{children}</dd>
    </div>
  );
}

export function List({ items }: { items: string[] }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export function Quiet({ children }: { children: ReactNode }) {
  return <p className="border-t py-8 text-graphite">{children}</p>;
}

export function FundEmpty({
  title = "No fund yet",
  detail = "Run make fund-init, then refresh.",
}: {
  title?: string;
  detail?: string;
}) {
  return (
    <div className="py-24">
      <p className="text-[32px] font-light tracking-[-0.02em]">{title}</p>
      <p className="mt-2 text-graphite">{detail}</p>
    </div>
  );
}
