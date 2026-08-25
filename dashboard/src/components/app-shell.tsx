"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Menu, Receipt } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/trades", label: "Trades", icon: Receipt },
] as const;

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function BrandMark({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <span
        aria-hidden
        className="flex size-7 items-center justify-center rounded-md bg-primary/15 font-mono text-[11px] font-semibold tracking-tight text-primary"
      >
        EC
      </span>
      <div className="flex flex-col leading-none">
        <span className="text-sm font-medium tracking-tight text-foreground">
          Edgecraft
        </span>
        <span className="mt-0.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
          Paper fund
        </span>
      </div>
    </div>
  );
}

function NavLinks({
  pathname,
  onNavigate,
  compact = false,
}: {
  pathname: string;
  onNavigate?: () => void;
  compact?: boolean;
}) {
  return (
    <nav className={cn("flex gap-0.5", compact ? "flex-row" : "flex-col")}>
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors",
              compact && "px-3",
              active
                ? "bg-sidebar-accent text-foreground"
                : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground"
            )}
            aria-current={active ? "page" : undefined}
          >
            <Icon className="size-3.5 shrink-0 opacity-80" />
            <span>{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const [mobileOpen, setMobileOpen] = React.useState(false);

  const pageMeta =
    pathname.startsWith("/trades")
      ? { title: "Trades", micro: "EXECUTION" }
      : { title: "Overview", micro: "PERFORMANCE" };

  return (
    <div className="flex min-h-full bg-background">
      {/* Desktop left rail */}
      <aside className="sticky top-0 hidden h-svh w-52 shrink-0 flex-col border-r border-border bg-sidebar md:flex">
        <div className="flex h-12 items-center border-b border-border px-3">
          <BrandMark />
        </div>
        <div className="flex flex-1 flex-col gap-4 p-2.5">
          <NavLinks pathname={pathname} />
        </div>
        <div className="border-t border-border px-3 py-2.5">
          <p className="font-mono text-[10px] text-muted-foreground">
            paper · $1,000 base
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className="sticky top-0 z-40 flex h-12 items-center gap-3 border-b border-border bg-background/95 px-4 backdrop-blur-sm supports-backdrop-filter:bg-background/80 md:px-6">
          {/* Mobile menu */}
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className="md:hidden"
                aria-label="Open navigation"
              >
                <Menu className="size-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-64 gap-0 p-0">
              <SheetHeader className="border-b border-border px-3 py-3 text-left">
                <SheetTitle className="sr-only">Navigation</SheetTitle>
                <BrandMark />
              </SheetHeader>
              <div className="p-2.5">
                <NavLinks
                  pathname={pathname}
                  onNavigate={() => setMobileOpen(false)}
                />
              </div>
            </SheetContent>
          </Sheet>

          <div className="flex min-w-0 flex-1 items-baseline gap-2">
            <span className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
              {pageMeta.micro}
            </span>
            <h1 className="truncate text-sm font-medium tracking-tight text-foreground">
              {pageMeta.title}
            </h1>
          </div>

          <div className="hidden items-center gap-2 sm:flex">
            <span className="rounded-md border border-border bg-card px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
              paper
            </span>
          </div>
        </header>

        {/* Mobile top tabs (secondary to sheet) */}
        <div className="flex border-b border-border px-2 py-1.5 md:hidden">
          <NavLinks pathname={pathname} compact />
        </div>

        <main className="flex-1 px-4 py-5 md:px-6 md:py-6">{children}</main>
      </div>
    </div>
  );
}
