"use client";

import * as React from "react";
import Link from "next/link";

import { capitalize, cycleHref, num } from "@/components/display";
import { formatDay, formatPrice, formatQty, formatTs, formatUsd } from "@/components/format";
import { Money, Page, PageTitle, Quiet, TableWrap } from "@/components/panel";
import type { OrderSide, TradeRow } from "@/lib/types";
import { cn } from "@/lib/utils";

export type NamedTrade = TradeRow & { name: string };

const SIDES: OrderSide[] = ["buy", "sell", "short", "cover", "settle"];

export function TradesView({ fundId, trades }: { fundId: string; trades: NamedTrade[] }) {
  const [search, setSearch] = React.useState("");
  const [side, setSide] = React.useState<OrderSide | null>(null);
  const [open, setOpen] = React.useState<string | null>(null);

  const sides = SIDES.filter((s) => trades.some((t) => t.side === s));
  const filtered = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    return trades.filter((t) => {
      if (side && t.side !== side) return false;
      if (!q) return true;
      return `${t.name} ${t.instrument_id} ${t.cycle_key}`.toLowerCase().includes(q);
    });
  }, [trades, search, side]);

  const fees = filtered.reduce((sum, t) => sum + num(t.fee), 0);
  const realized = filtered.reduce((sum, t) => sum + num(t.realized_pnl), 0);

  return (
    <Page className="gap-10">
      <PageTitle
        aside={
          trades.length ? (
            <>
              {filtered.length} {filtered.length === 1 ? "fill" : "fills"}, {formatUsd(fees)} in fees,{" "}
              <Money value={realized} /> realized
            </>
          ) : null
        }
      >
        Trades
      </PageTitle>

      {trades.length === 0 ? (
        <Quiet>No trades yet. Fills appear after a decision places orders.</Quiet>
      ) : (
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search contracts"
              aria-label="Search contracts"
              className="w-full rounded-full border bg-transparent px-4 py-2 text-[14px] placeholder:text-mist hover:border-mist focus:border-mist focus:outline-none sm:w-72"
            />
            <div className="flex flex-wrap gap-1.5 text-[14px]">
              {[null, ...sides].map((s) => (
                <button
                  key={s ?? "all"}
                  type="button"
                  aria-pressed={side === s}
                  onClick={() => setSide(s)}
                  className={cn(
                    "rounded-full border px-3.5 py-1.5 transition-colors",
                    side === s ? "border-ink text-ink" : "border-transparent text-graphite hover:text-ink",
                  )}
                >
                  {s ? capitalize(s) : "All"}
                </button>
              ))}
            </div>
          </div>

          {filtered.length === 0 ? (
            <Quiet>Nothing matches. Try another search.</Quiet>
          ) : (
            <TableWrap>
              <table className="ledger">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Contract</th>
                    <th>Side</th>
                    <th className="num">Quantity</th>
                    <th className="num">Price</th>
                    <th className="num">Fee</th>
                    <th className="num">Realized</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row) => {
                    const key = `${row.cycle_key}:${row.fill_id}`;
                    const expanded = open === key;
                    return (
                      <React.Fragment key={key}>
                        <tr
                          className="link-row cursor-pointer"
                          onClick={() => setOpen(expanded ? null : key)}
                          aria-expanded={expanded}
                        >
                          <td className="whitespace-nowrap text-graphite">{formatDay(row.as_of)}</td>
                          <td className="min-w-56">{row.name}</td>
                          <td>{capitalize(row.side)}</td>
                          <td className="num">{formatQty(row.quantity)}</td>
                          <td className="num">{formatPrice(row.execution_price, row.asset_class)}</td>
                          <td className="num text-graphite">{formatUsd(row.fee)}</td>
                          <td className="num"><Money value={row.realized_pnl} /></td>
                        </tr>
                        {expanded ? (
                          <tr>
                            <td colSpan={7} className="!border-t-0 pt-0 pb-5">
                              <dl className="grid grid-cols-2 gap-x-8 gap-y-3 rounded-lg bg-wash p-4 text-sm sm:grid-cols-4">
                                <div>
                                  <dt className="text-graphite">Filled</dt>
                                  <dd>{formatTs(row.as_of)}</dd>
                                </div>
                                <div>
                                  <dt className="text-graphite">Quoted at</dt>
                                  <dd>{formatPrice(row.quote_price, row.asset_class)}</dd>
                                </div>
                                <div>
                                  <dt className="text-graphite">Cost</dt>
                                  <dd>{formatUsd(row.gross_notional)}</dd>
                                </div>
                                <div>
                                  <dt className="text-graphite">Cash change</dt>
                                  <dd><Money value={row.cash_delta} /></dd>
                                </div>
                                <div className="col-span-2 sm:col-span-4">
                                  <Link href={cycleHref(row.cycle_key, fundId)} className="text-fund hover:underline">
                                    See the decision behind this trade
                                  </Link>
                                </div>
                              </dl>
                            </td>
                          </tr>
                        ) : null}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </TableWrap>
          )}
        </div>
      )}
    </Page>
  );
}
