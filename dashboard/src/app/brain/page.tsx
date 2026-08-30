import Link from "next/link";

import {
  actionBadgeClass,
  cycleHref,
  num,
  openPositions,
  outcomeBadgeClass,
  pnlClass,
  stanceBadgeClass,
} from "@/components/display";
import {
  formatPct,
  formatQty,
  formatTs,
  formatUsd,
} from "@/components/format";
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
import {
  fundBrain,
  getDefaultFund,
  getLatestState,
  listCycles,
  listEvents,
} from "@/lib/fund";
import { cn } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export default async function BrainPage() {
  const fund = getDefaultFund();
  if (!fund) return <FundEmpty />;

  const cycles = listCycles(fund.fund_id);
  const state = getLatestState(fund.fund_id);
  if (!state) return <FundEmpty title="No fund state" />;

  const events = listEvents(fund.fund_id);
  const brain = fundBrain(fund.fund_id, state, cycles, events);
  const open = openPositions(state.positions);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <header className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
              Memory
            </span>
            <h2 className="text-sm font-medium text-foreground">Fund brain</h2>
          </div>
          <p className="mt-0.5 font-mono text-xs text-muted-foreground tabular-nums">
            {fund.fund_id} · compact ledger feedback for the next cycle
          </p>
        </div>
        <p className="font-mono text-xs text-muted-foreground tabular-nums">
          {brain.schema_version}
        </p>
      </header>

      <p className="rounded-lg border border-border bg-card px-3.5 py-2.5 text-xs leading-relaxed text-muted-foreground">
        {brain.learning_boundary}
      </p>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg border border-border bg-card px-3.5 py-3">
          <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Cash weight
          </p>
          <p className="mt-1 font-mono text-lg tabular-nums">
            {formatPct(brain.activity.cash_nav_weight)}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card px-3.5 py-3">
          <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Open / idle
          </p>
          <p className="mt-1 font-mono text-lg tabular-nums">
            {brain.activity.open_position_count}
            <span className="ml-2 text-xs text-muted-foreground">
              {brain.activity.idle_cash ? "idle cash" : "deployed"}
            </span>
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card px-3.5 py-3">
          <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Recent trades
          </p>
          <p className="mt-1 font-mono text-lg tabular-nums">
            {brain.activity.recent_trade_cycles}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card px-3.5 py-3">
          <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            All-cash holds
          </p>
          <p className="mt-1 font-mono text-lg tabular-nums">
            {brain.activity.consecutive_all_cash_holds}
          </p>
        </div>
      </section>

      <Panel
        micro="Prompts"
        title="Adaptive next-cycle notes"
        trailing={`${brain.adaptive_prompts.length}`}
        bodyClassName="px-3.5 py-3"
      >
        <ol className="list-decimal space-y-2 pl-4 text-sm leading-relaxed">
          {brain.adaptive_prompts.map((prompt) => (
            <li key={prompt}>{prompt}</li>
          ))}
        </ol>
      </Panel>

      <Panel
        micro="Outcomes"
        title="Recent cycle memory"
        trailing="NAV change is feedback, not skill"
      >
        {brain.recent_cycles.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-muted-foreground">
            No cycle memory yet.
          </p>
        ) : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-3.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  cycle
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  action
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  what_changed
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  ending nav
                </TableHead>
                <TableHead className="pr-3.5 text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  next nav Δ
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...brain.recent_cycles].reverse().map((item) => {
                const delta = num(item.next_cycle_nav_change);
                return (
                  <TableRow key={item.cycle_key}>
                    <TableCell className="pl-3.5 font-mono">
                      <Link
                        href={cycleHref(item.cycle_key)}
                        className="hover:underline"
                      >
                        {item.cycle_key}
                      </Link>
                      <div className="font-mono text-[10px] text-muted-foreground tabular-nums">
                        {formatTs(item.as_of)}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={cn(
                          "font-mono text-[10px] capitalize",
                          actionBadgeClass(item.action),
                        )}
                      >
                        {item.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-[28rem] truncate text-muted-foreground">
                      {item.what_changed || item.thesis}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatUsd(item.ending_nav)}
                    </TableCell>
                    <TableCell className="pr-3.5 text-right">
                      <Badge
                        variant="outline"
                        className={cn(
                          "font-mono text-[10px] capitalize",
                          outcomeBadgeClass(item.next_cycle_outcome),
                        )}
                      >
                        {item.next_cycle_outcome}
                      </Badge>
                      {item.next_cycle_nav_change != null ? (
                        <div
                          className={cn(
                            "mt-0.5 font-mono tabular-nums",
                            pnlClass(delta),
                          )}
                        >
                          {formatUsd(item.next_cycle_nav_change, {
                            signed: true,
                          })}
                        </div>
                      ) : null}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Panel>

      <Panel
        micro="Instruments"
        title="Position memory"
        trailing={`${brain.instruments.length} · ${open.length} open`}
      >
        {brain.instruments.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-muted-foreground">
            No instrument memory yet.
          </p>
        ) : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-3.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Instrument
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Stance
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Qty
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Unrealized
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Realized
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Fills
                </TableHead>
                <TableHead className="pr-3.5 text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Exits W/L
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {brain.instruments.map((item) => {
                const realized = num(item.realized_pnl);
                const unrealized = num(item.current_unrealized_pnl);
                return (
                  <TableRow key={item.instrument_id}>
                    <TableCell className="pl-3.5 font-mono font-medium">
                      {item.instrument_id}
                      <div className="font-mono text-[10px] text-muted-foreground capitalize">
                        {item.asset_class}
                      </div>
                    </TableCell>
                    <TableCell>
                      {item.latest_hypothesis ? (
                        <Badge
                          variant="outline"
                          className={cn(
                            "font-mono text-[10px] capitalize",
                            stanceBadgeClass(item.latest_hypothesis.stance),
                          )}
                        >
                          {item.latest_hypothesis.stance}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatQty(item.current_quantity)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-mono tabular-nums",
                        pnlClass(unrealized),
                      )}
                    >
                      {item.current_unrealized_pnl != null
                        ? formatUsd(item.current_unrealized_pnl, {
                            signed: true,
                          })
                        : "—"}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-mono tabular-nums",
                        pnlClass(realized),
                      )}
                    >
                      {formatUsd(item.realized_pnl, { signed: true })}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {item.simulated_fill_count}
                    </TableCell>
                    <TableCell className="pr-3.5 text-right font-mono tabular-nums">
                      {item.profitable_exit_count}/{item.losing_exit_count}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Panel>

      <Panel
        micro="Rejections"
        title="Recent rejected cycles"
        trailing={`${brain.recent_rejections.length}`}
      >
        {brain.recent_rejections.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-muted-foreground">
            No cycle_rejected events in the hash chain.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {brain.recent_rejections.map((item, i) => (
              <li key={`${item.cycle_key ?? "none"}:${i}`} className="px-3.5 py-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-mono text-xs">
                    {item.cycle_key ?? "(no key)"}
                  </span>
                  <Badge
                    variant="outline"
                    className="font-mono text-[10px] text-danger"
                  >
                    {item.error_type}
                  </Badge>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  {item.reason}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
