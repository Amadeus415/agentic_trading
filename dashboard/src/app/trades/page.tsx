/**
 * Every simulated fill and settlement, newest first (read-only).
 */
import { contractName, contractTitles } from "@/components/display";
import { FundEmpty } from "@/components/panel";
import { TradesView } from "@/components/trades-view";
import { extractFillsFromCycles, getSelectedFund, listCycles, type FundSearchParams } from "@/lib/fund";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export default async function TradesPage({ searchParams }: { searchParams: FundSearchParams }) {
  const fund = await getSelectedFund(searchParams);
  if (!fund) return <FundEmpty />;

  const cycles = listCycles(fund.fund_id);
  const titles = contractTitles(cycles);
  const trades = [...extractFillsFromCycles(cycles)]
    .reverse()
    .map((row) => ({ ...row, name: contractName(titles, row.instrument_id, row.asset_class) }));

  return <TradesView fundId={fund.fund_id} trades={trades} />;
}
