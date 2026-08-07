/**
 * Trades inspection — all paper fills + cycle decision metadata (read-only).
 */
import { TradesView, type CycleTradeMeta } from "@/components/trades-view";
import {
  extractFillsFromCycles,
  listCycles,
  listFunds,
  toCycleListItems,
} from "@/lib/fund";
import type { TradeRow } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export default async function TradesPage() {
  const funds = listFunds();
  const fund = funds[0] ?? null;

  if (!fund) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
        <section className="rounded-lg border border-border bg-card px-4 py-10 text-center">
          <p className="text-sm font-medium text-foreground">No funds found</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Initialize the paper fund ledger, then refresh this page.
          </p>
        </section>
      </div>
    );
  }

  const cycles = listCycles(fund.fund_id);
  // Newest fills first (extractFillsFromCycles is oldest→newest).
  const trades: TradeRow[] = [...extractFillsFromCycles(cycles)].reverse();

  const thesisByKey = new Map(
    cycles.map((c) => [c.cycle_key, String(c.decision?.thesis ?? "")] as const),
  );
  // Newest cycles first for the cycles tab.
  const cycleMeta: CycleTradeMeta[] = toCycleListItems(cycles)
    .reverse()
    .map((item) => ({
      ...item,
      thesis: thesisByKey.get(item.cycle_key) ?? "",
    }));

  return (
    <TradesView
      fundId={fund.fund_id}
      trades={trades}
      cycles={cycleMeta}
    />
  );
}
