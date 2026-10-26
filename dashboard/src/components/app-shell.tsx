"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { cn } from "@/lib/utils";

const FUND_LABELS: Record<string, string> = {
  "edgecraft-facts": "Facts",
  "edgecraft-predictions": "v2 predictions",
  "edgecraft-baseline": "Baseline",
  "edgecraft-aggressive": "v1 archive",
};

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/trades", label: "Trades" },
  { href: "/cycles", label: "Decisions" },
  { href: "/attribution", label: "Scorecard" },
  { href: "/brain", label: "Memory" },
] as const;

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children, funds }: { children: React.ReactNode; funds: string[] }) {
  const params = useSearchParams();
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const selected =
    params.get("fund") ?? ["edgecraft-facts", "edgecraft-predictions"].find((fund) => funds.includes(fund)) ?? funds[0];
  const query = params.get("fund") ? `?fund=${encodeURIComponent(params.get("fund")!)}` : "";

  function switchFund(fund: string) {
    // Decision keys and positions belong to one fund, so a detail page falls back to its list.
    const base = pathname.startsWith("/cycles/") ? "/cycles" : pathname.startsWith("/positions/") ? "/" : pathname;
    router.push(`${base}?fund=${encodeURIComponent(fund)}`);
  }

  return (
    <div className="mx-auto flex min-h-svh w-full max-w-[1040px] flex-col px-4 sm:px-8">
      <header className="flex flex-wrap items-center gap-x-10 gap-y-3 border-b py-5">
        <Link href={`/${query}`} className="flex items-center gap-2.5 text-[15px] font-semibold tracking-[-0.01em]">
          <svg aria-hidden viewBox="0 0 20 20" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.25">
            <path d="M2 15 L7 9 L11 12 L18 4" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M2 18 H18" className="text-mist" stroke="currentColor" />
          </svg>
          Edgecraft
        </Link>

        <nav className="order-3 -mx-4 flex w-[calc(100%+2rem)] gap-6 overflow-x-auto px-4 text-[14px] sm:order-none sm:mx-0 sm:w-auto sm:px-0">
          {NAV.map(({ href, label }) => {
            const active = isActive(pathname, href);
            return (
              <Link
                key={href}
                href={`${href}${query}`}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "shrink-0 py-1 transition-colors",
                  active ? "text-ink underline decoration-1 underline-offset-[10px]" : "text-graphite hover:text-ink",
                )}
              >
                {label}
              </Link>
            );
          })}
        </nav>

        {funds.length > 0 ? (
          <label className="relative ml-auto flex items-center text-[14px] text-graphite">
            <span className="sr-only">Fund</span>
            <select
              value={selected}
              onChange={(event) => switchFund(event.target.value)}
              className="cursor-pointer appearance-none rounded-full border bg-transparent py-1.5 pr-8 pl-3.5 text-ink hover:border-mist"
            >
              {funds.map((fund) => (
                <option key={fund} value={fund}>
                  {FUND_LABELS[fund] ?? fund}
                </option>
              ))}
            </select>
            <svg aria-hidden viewBox="0 0 12 12" className="pointer-events-none absolute right-3 size-3" fill="none" stroke="currentColor" strokeWidth="1.25">
              <path d="M3 4.5 L6 7.5 L9 4.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </label>
        ) : null}
      </header>

      <main className="flex-1 py-12 sm:py-16">{children}</main>

      <footer className="border-t py-6 text-[13px] text-mist">
        Paper money. Every trade is simulated.
      </footer>
    </div>
  );
}
