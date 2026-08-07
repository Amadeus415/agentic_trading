"use client";

import * as React from "react";
import { Search, X } from "lucide-react";

import {
  formatQty,
  formatTs,
  formatUsd,
} from "@/components/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { CycleListItem, OrderSide, TradeRow } from "@/lib/types";
import { cn } from "@/lib/utils";

const SIDES: OrderSide[] = ["buy", "sell", "short", "cover"];

export type CycleTradeMeta = CycleListItem & {
  /** Full thesis from decision payload when present. */
  thesis: string;
};

function num(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

function pnlClass(value: number): string {
  if (value > 0) return "text-success";
  if (value < 0) return "text-danger";
  return "text-muted-foreground";
}

function truncateId(id: string, head = 8): string {
  if (!id) return "—";
  if (id.length <= head + 4) return id;
  return `${id.slice(0, head)}…`;
}

function sideBadgeClass(side: string): string {
  switch (side) {
    case "buy":
      return "border-success/30 bg-success/15 text-success";
    case "sell":
      return "border-danger/30 bg-danger/15 text-danger";
    case "short":
      return "border-amber-500/30 bg-amber-500/15 text-amber-300";
    case "cover":
      return "border-indigo-400/30 bg-indigo-400/15 text-indigo-300";
    case "settle":
      return "border-border bg-muted text-muted-foreground";
    default:
      return "border-border bg-secondary text-secondary-foreground";
  }
}

function actionBadgeClass(action: string): string {
  if (action === "trade") return "border-indigo-400/30 bg-indigo-400/10 text-indigo-300";
  if (action === "hold") return "border-border bg-muted text-muted-foreground";
  return "border-border bg-secondary text-secondary-foreground";
}

type Summary = {
  total: number;
  buys: number;
  sells: number;
  shorts: number;
  covers: number;
  totalFees: number;
  realizedPnl: number;
};

function summarize(rows: TradeRow[]): Summary {
  const s: Summary = {
    total: rows.length,
    buys: 0,
    sells: 0,
    shorts: 0,
    covers: 0,
    totalFees: 0,
    realizedPnl: 0,
  };
  for (const r of rows) {
    if (r.side === "buy") s.buys += 1;
    else if (r.side === "sell") s.sells += 1;
    else if (r.side === "short") s.shorts += 1;
    else if (r.side === "cover") s.covers += 1;
    s.totalFees += num(r.fee);
    s.realizedPnl += num(r.realized_pnl);
  }
  return s;
}

function fillToJson(row: TradeRow): Record<string, unknown> {
  return {
    fill_id: row.fill_id,
    fund_id: row.fund_id,
    cycle_key: row.cycle_key,
    as_of: row.as_of,
    instrument_id: row.instrument_id,
    asset_class: row.asset_class,
    side: row.side,
    quantity: row.quantity,
    quote_price: row.quote_price,
    execution_price: row.execution_price,
    gross_notional: row.gross_notional,
    fee: row.fee,
    cash_delta: row.cash_delta,
    realized_pnl: row.realized_pnl,
    quote_id: row.quote_id,
    is_settlement: row.is_settlement,
  };
}

function Chip({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 rounded-md border border-border bg-card px-2.5 py-1.5">
      <span className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
        {label}
      </span>
      <span
        className={cn(
          "font-mono text-sm font-medium tabular-nums text-foreground",
          valueClass,
        )}
      >
        {value}
      </span>
    </div>
  );
}

export function TradesView({
  fundId,
  trades,
  cycles,
}: {
  fundId: string;
  trades: TradeRow[];
  cycles: CycleTradeMeta[];
}) {
  const [search, setSearch] = React.useState("");
  const [sides, setSides] = React.useState<Set<OrderSide>>(new Set());
  const [assetClass, setAssetClass] = React.useState<string>("all");
  const [cycleKey, setCycleKey] = React.useState<string>("all");
  const [selected, setSelected] = React.useState<TradeRow | null>(null);
  const [tab, setTab] = React.useState<"fills" | "cycles">("fills");

  const cycleByKey = React.useMemo(() => {
    const map = new Map<string, CycleTradeMeta>();
    for (const c of cycles) map.set(c.cycle_key, c);
    return map;
  }, [cycles]);

  const assetClasses = React.useMemo(() => {
    const set = new Set<string>();
    for (const t of trades) {
      if (t.asset_class) set.add(t.asset_class);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [trades]);

  const cycleOptions = React.useMemo(() => {
    // Newest first (cycles already sorted newest-first from server)
    return cycles.map((c) => c.cycle_key);
  }, [cycles]);

  const filtered = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    return trades.filter((t) => {
      if (sides.size > 0 && !sides.has(t.side as OrderSide)) return false;
      if (assetClass !== "all" && t.asset_class !== assetClass) return false;
      if (cycleKey !== "all" && t.cycle_key !== cycleKey) return false;
      if (q) {
        const hay = `${t.instrument_id} ${t.fill_id} ${t.cycle_key} ${t.asset_class}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [trades, search, sides, assetClass, cycleKey]);

  const summary = React.useMemo(() => summarize(filtered), [filtered]);

  function toggleSide(side: OrderSide) {
    setSides((prev) => {
      const next = new Set(prev);
      if (next.has(side)) next.delete(side);
      else next.add(side);
      return next;
    });
  }

  function clearFilters() {
    setSearch("");
    setSides(new Set());
    setAssetClass("all");
    setCycleKey("all");
  }

  function selectCycle(key: string) {
    setCycleKey(key);
    setTab("fills");
  }

  const hasActiveFilters =
    search.trim() !== "" ||
    sides.size > 0 ||
    assetClass !== "all" ||
    cycleKey !== "all";

  const selectedCycle = selected
    ? cycleByKey.get(selected.cycle_key) ?? null
    : null;

  const emptyAll = trades.length === 0;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <header className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
              All fills
            </span>
            <h2 className="text-sm font-medium text-foreground">Trades</h2>
          </div>
          <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground tabular-nums">
            {fundId}
          </p>
        </div>
        <p className="font-mono text-xs text-muted-foreground tabular-nums">
          {trades.length} fill{trades.length === 1 ? "" : "s"} · {cycles.length}{" "}
          cycle{cycles.length === 1 ? "" : "s"}
        </p>
      </header>

      <Tabs
        value={tab}
        onValueChange={(v) => setTab(v as "fills" | "cycles")}
        className="gap-3"
      >
        <TabsList variant="line" className="w-full justify-start sm:w-auto">
          <TabsTrigger value="fills" className="px-3">
            Fills
          </TabsTrigger>
          <TabsTrigger value="cycles" className="px-3">
            Cycles
          </TabsTrigger>
        </TabsList>

        <TabsContent value="fills" className="flex flex-col gap-3">
          {/* Summary chips */}
          <section
            aria-label="Fill summary"
            className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7"
          >
            <Chip label="Fills" value={String(summary.total)} />
            <Chip label="Buys" value={String(summary.buys)} />
            <Chip label="Sells" value={String(summary.sells)} />
            <Chip label="Shorts" value={String(summary.shorts)} />
            <Chip label="Covers" value={String(summary.covers)} />
            <Chip label="Total fees" value={formatUsd(summary.totalFees)} />
            <Chip
              label="Realized PnL"
              value={formatUsd(summary.realizedPnl, { signed: true })}
              valueClass={pnlClass(summary.realizedPnl)}
            />
          </section>

          {/* Toolbar filters */}
          <section
            aria-label="Trade filters"
            className="flex flex-col gap-2 rounded-lg border border-border bg-card p-2.5"
          >
            <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search instrument, fill id, cycle…"
                  className="h-8 pl-8 font-mono text-xs"
                  aria-label="Search instrument"
                />
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                {SIDES.map((side) => {
                  const active = sides.has(side);
                  return (
                    <Button
                      key={side}
                      type="button"
                      size="xs"
                      variant={active ? "default" : "outline"}
                      onClick={() => toggleSide(side)}
                      className={cn(
                        "font-mono text-[10px] capitalize",
                        active && sideBadgeClass(side),
                      )}
                      aria-pressed={active}
                    >
                      {side}
                    </Button>
                  );
                })}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Select value={assetClass} onValueChange={setAssetClass}>
                  <SelectTrigger
                    size="sm"
                    className="min-w-[8.5rem] font-mono text-xs"
                    aria-label="Filter asset class"
                  >
                    <SelectValue placeholder="Asset class" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All classes</SelectItem>
                    {assetClasses.map((ac) => (
                      <SelectItem key={ac} value={ac} className="capitalize">
                        {ac}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Select value={cycleKey} onValueChange={setCycleKey}>
                  <SelectTrigger
                    size="sm"
                    className="min-w-[10rem] max-w-[14rem] font-mono text-xs"
                    aria-label="Filter cycle key"
                  >
                    <SelectValue placeholder="Cycle" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All cycles</SelectItem>
                    {cycleOptions.map((key) => (
                      <SelectItem key={key} value={key}>
                        {key}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {hasActiveFilters ? (
                  <Button
                    type="button"
                    size="xs"
                    variant="ghost"
                    onClick={clearFilters}
                    className="gap-1 text-muted-foreground"
                  >
                    <X className="size-3" />
                    Clear
                  </Button>
                ) : null}
              </div>
            </div>
            {cycleKey !== "all" ? (
              <p className="font-mono text-[10px] text-muted-foreground">
                Filtered to cycle{" "}
                <span className="text-foreground">{cycleKey}</span>
              </p>
            ) : null}
          </section>

          {/* Fills table */}
          <section
            aria-label="Trade history"
            className="flex min-h-[280px] flex-col rounded-lg border border-border bg-card"
          >
            <div className="flex items-center justify-between border-b border-border px-3.5 py-2.5">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
                  Ledger
                </span>
                <h3 className="text-sm font-medium text-foreground">Fills</h3>
              </div>
              <span className="font-mono text-xs text-muted-foreground tabular-nums">
                {filtered.length}
                {hasActiveFilters ? ` / ${trades.length}` : ""} shown · newest
                first
              </span>
            </div>

            {emptyAll ? (
              <div className="flex flex-1 items-center justify-center px-4 py-12">
                <div className="max-w-sm text-center">
                  <p className="text-sm font-medium text-foreground">
                    No fills yet
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Simulated trades will appear here after the paper fund
                    executes a cycle with orders.
                  </p>
                </div>
              </div>
            ) : filtered.length === 0 ? (
              <div className="flex flex-1 items-center justify-center px-4 py-12">
                <div className="max-w-sm text-center">
                  <p className="text-sm font-medium text-foreground">
                    No matching fills
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Adjust or clear filters to see more rows.
                  </p>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="mt-3"
                    onClick={clearFilters}
                  >
                    Clear filters
                  </Button>
                </div>
              </div>
            ) : (
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    {(
                      [
                        ["as_of", "left"],
                        ["cycle_key", "left"],
                        ["instrument_id", "left"],
                        ["asset_class", "left"],
                        ["side", "left"],
                        ["quantity", "right"],
                        ["execution_price", "right"],
                        ["gross_notional", "right"],
                        ["fee", "right"],
                        ["realized_pnl", "right"],
                        ["cash_delta", "right"],
                        ["fill_id", "right"],
                      ] as const
                    ).map(([col, align], i) => (
                      <TableHead
                        key={col}
                        className={cn(
                          "h-8 font-mono text-[10px] tracking-wider text-muted-foreground uppercase",
                          align === "right" && "text-right",
                          i === 0 && "pl-3.5",
                          i === 11 && "pr-3.5",
                        )}
                      >
                        {col}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((row) => {
                    const rpnl = num(row.realized_pnl);
                    const cash = num(row.cash_delta);
                    return (
                      <TableRow
                        key={`${row.cycle_key}:${row.fill_id}`}
                        className="cursor-pointer"
                        onClick={() => setSelected(row)}
                        data-state={
                          selected?.fill_id === row.fill_id ? "selected" : undefined
                        }
                      >
                        <TableCell className="pl-3.5 font-mono tabular-nums text-muted-foreground">
                          {formatTs(row.as_of)}
                        </TableCell>
                        <TableCell className="max-w-[9rem] truncate font-mono text-muted-foreground">
                          {row.cycle_key}
                        </TableCell>
                        <TableCell className="font-mono font-medium tabular-nums">
                          {row.instrument_id}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="secondary"
                            className="font-mono text-[10px] capitalize"
                          >
                            {row.asset_class || "—"}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={cn(
                              "font-mono text-[10px] capitalize",
                              sideBadgeClass(row.side),
                            )}
                          >
                            {row.side}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {formatQty(row.quantity)}
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {formatUsd(row.execution_price)}
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {formatUsd(row.gross_notional)}
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums text-muted-foreground">
                          {formatUsd(row.fee)}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right font-mono tabular-nums",
                            pnlClass(rpnl),
                          )}
                        >
                          {formatUsd(row.realized_pnl, { signed: true })}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right font-mono tabular-nums",
                            pnlClass(cash),
                          )}
                        >
                          {formatUsd(row.cash_delta, { signed: true })}
                        </TableCell>
                        <TableCell className="pr-3.5 text-right font-mono text-[10px] text-muted-foreground tabular-nums">
                          {truncateId(row.fill_id)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </section>
        </TabsContent>

        <TabsContent value="cycles" className="flex flex-col gap-3">
          <section
            aria-label="Cycles"
            className="flex min-h-[280px] flex-col rounded-lg border border-border bg-card"
          >
            <div className="flex items-center justify-between border-b border-border px-3.5 py-2.5">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
                  Decision log
                </span>
                <h3 className="text-sm font-medium text-foreground">Cycles</h3>
              </div>
              <span className="font-mono text-xs text-muted-foreground tabular-nums">
                click filters fills
              </span>
            </div>

            {cycles.length === 0 ? (
              <div className="flex flex-1 items-center justify-center px-4 py-12">
                <p className="text-center text-sm text-muted-foreground">
                  No cycles recorded yet.
                </p>
              </div>
            ) : (
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="h-8 pl-3.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                      as_of
                    </TableHead>
                    <TableHead className="h-8 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                      cycle_key
                    </TableHead>
                    <TableHead className="h-8 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                      action
                    </TableHead>
                    <TableHead className="h-8 text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                      nav after
                    </TableHead>
                    <TableHead className="h-8 pr-3.5 text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                      fills
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {cycles.map((c) => {
                    const active = cycleKey === c.cycle_key;
                    return (
                      <TableRow
                        key={c.cycle_key}
                        className={cn(
                          "cursor-pointer",
                          active && "bg-muted/60",
                        )}
                        onClick={() => selectCycle(c.cycle_key)}
                        data-state={active ? "selected" : undefined}
                      >
                        <TableCell className="pl-3.5 font-mono tabular-nums text-muted-foreground">
                          {formatTs(c.as_of)}
                        </TableCell>
                        <TableCell className="font-mono font-medium">
                          {c.cycle_key}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={cn(
                              "font-mono text-[10px] capitalize",
                              actionBadgeClass(c.action),
                            )}
                          >
                            {c.action}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {c.nav != null ? formatUsd(c.nav) : "—"}
                        </TableCell>
                        <TableCell className="pr-3.5 text-right font-mono tabular-nums">
                          {c.fill_count}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </section>

          {cycleKey !== "all" ? (
            <div className="flex items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2">
              <p className="font-mono text-xs text-muted-foreground">
                Fills filtered to{" "}
                <span className="text-foreground">{cycleKey}</span>
              </p>
              <div className="flex gap-1.5">
                <Button
                  type="button"
                  size="xs"
                  variant="outline"
                  onClick={() => setTab("fills")}
                >
                  View fills
                </Button>
                <Button
                  type="button"
                  size="xs"
                  variant="ghost"
                  onClick={() => setCycleKey("all")}
                >
                  Clear
                </Button>
              </div>
            </div>
          ) : null}
        </TabsContent>
      </Tabs>

      {/* Detail sheet */}
      <Sheet
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <SheetContent
          side="right"
          className="w-full gap-0 p-0 sm:max-w-lg"
        >
          {selected ? (
            <>
              <SheetHeader className="border-b border-border px-4 py-3 text-left">
                <SheetTitle className="font-mono text-sm">
                  {selected.instrument_id}{" "}
                  <span className="text-muted-foreground">·</span>{" "}
                  <span className="capitalize">{selected.side}</span>
                </SheetTitle>
                <SheetDescription className="font-mono text-xs tabular-nums">
                  {selected.fill_id}
                </SheetDescription>
              </SheetHeader>

              <ScrollArea className="min-h-0 flex-1">
                <div className="flex flex-col gap-4 p-4">
                  <div className="grid grid-cols-2 gap-2">
                    <Chip label="as_of" value={formatTs(selected.as_of)} />
                    <Chip label="cycle" value={selected.cycle_key} />
                    <Chip
                      label="qty"
                      value={formatQty(selected.quantity)}
                    />
                    <Chip
                      label="exec px"
                      value={formatUsd(selected.execution_price)}
                    />
                    <Chip
                      label="gross"
                      value={formatUsd(selected.gross_notional)}
                    />
                    <Chip label="fee" value={formatUsd(selected.fee)} />
                    <Chip
                      label="realized"
                      value={formatUsd(selected.realized_pnl, {
                        signed: true,
                      })}
                      valueClass={pnlClass(num(selected.realized_pnl))}
                    />
                    <Chip
                      label="cash Δ"
                      value={formatUsd(selected.cash_delta, { signed: true })}
                      valueClass={pnlClass(num(selected.cash_delta))}
                    />
                  </div>

                  <div className="rounded-lg border border-border bg-muted/30 p-3">
                    <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                      Parent cycle
                    </p>
                    {selectedCycle ? (
                      <div className="mt-2 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge
                            variant="outline"
                            className={cn(
                              "font-mono text-[10px] capitalize",
                              actionBadgeClass(selectedCycle.action),
                            )}
                          >
                            {selectedCycle.action}
                          </Badge>
                          <span className="font-mono text-xs text-muted-foreground tabular-nums">
                            {formatTs(selectedCycle.as_of)}
                          </span>
                          {selectedCycle.nav != null ? (
                            <span className="font-mono text-xs tabular-nums">
                              NAV {formatUsd(selectedCycle.nav)}
                            </span>
                          ) : null}
                        </div>
                        <p className="text-sm leading-relaxed text-foreground">
                          {selectedCycle.thesis ||
                            selectedCycle.decision_summary.thesis_snippet ||
                            "No thesis recorded for this cycle."}
                        </p>
                        <Button
                          type="button"
                          size="xs"
                          variant="outline"
                          className="font-mono"
                          onClick={() => {
                            setSelected(null);
                            selectCycle(selected.cycle_key);
                          }}
                        >
                          Filter fills to cycle
                        </Button>
                      </div>
                    ) : (
                      <p className="mt-2 text-sm text-muted-foreground">
                        Cycle metadata unavailable.
                      </p>
                    )}
                  </div>

                  <div>
                    <p className="mb-1.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                      Fill JSON
                    </p>
                    <pre className="overflow-x-auto rounded-lg border border-border bg-background p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
                      {JSON.stringify(fillToJson(selected), null, 2)}
                    </pre>
                  </div>
                </div>
              </ScrollArea>
            </>
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  );
}
