import Link from "next/link";

import { actionBadgeClass, cycleHref } from "@/components/display";
import { formatTs, formatUsd } from "@/components/format";
import { FundEmpty, Panel } from "@/components/panel";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getDefaultFund, listCycles, toCycleListItems } from "@/lib/fund";
import { cn } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export default async function CyclesPage() {
  const fund = getDefaultFund();
  if (!fund) return <FundEmpty />;

  const cycles = toCycleListItems(listCycles(fund.fund_id)).reverse();
  const trades = cycles.filter((c) => c.action === "trade").length;
  const holds = cycles.filter((c) => c.action === "hold").length;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <header className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
              Decision log
            </span>
            <h2 className="text-sm font-medium text-foreground">Cycles</h2>
          </div>
          <p className="mt-0.5 font-mono text-xs text-muted-foreground tabular-nums">
            {fund.fund_id}
          </p>
        </div>
        <p className="font-mono text-xs text-muted-foreground tabular-nums">
          {cycles.length} cycles · {trades} trade · {holds} hold
        </p>
      </header>

      <Panel micro="Ledger" title="Completed cycles" trailing="newest first">
        {cycles.length === 0 ? (
          <p className="px-4 py-12 text-center text-sm text-muted-foreground">
            No cycles recorded yet.
          </p>
        ) : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-3.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  as_of
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  cycle_key
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  action
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  thesis
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  what_changed
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  nav
                </TableHead>
                <TableHead className="pr-3.5 text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  fills
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {cycles.map((c) => (
                <TableRow key={c.cycle_key}>
                  <TableCell className="pl-3.5 font-mono tabular-nums text-muted-foreground">
                    {formatTs(c.as_of)}
                  </TableCell>
                  <TableCell className="font-mono font-medium">
                    <Link
                      href={cycleHref(c.cycle_key)}
                      className="hover:underline"
                    >
                      {c.cycle_key}
                    </Link>
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
                  <TableCell className="max-w-[22rem] truncate text-muted-foreground">
                    {c.decision_summary.thesis_snippet || "—"}
                  </TableCell>
                  <TableCell className="max-w-[18rem] truncate text-muted-foreground">
                    {c.what_changed || "—"}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {c.nav != null ? formatUsd(c.nav) : "—"}
                  </TableCell>
                  <TableCell className="pr-3.5 text-right font-mono tabular-nums">
                    {c.fill_count}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Panel>
    </div>
  );
}
