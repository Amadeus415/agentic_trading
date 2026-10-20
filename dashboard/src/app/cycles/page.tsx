import Link from "next/link";

import { actionLabel, cycleHref } from "@/components/display";
import { formatDay, formatUsd } from "@/components/format";
import { FundEmpty, Page, PageTitle, Quiet } from "@/components/panel";
import { getSelectedFund, type FundSearchParams, listCycles, toCycleListItems } from "@/lib/fund";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export default async function CyclesPage({ searchParams }: { searchParams: FundSearchParams }) {
  const fund = await getSelectedFund(searchParams);
  if (!fund) return <FundEmpty />;

  const cycles = toCycleListItems(listCycles(fund.fund_id)).reverse();
  const trades = cycles.filter((c) => c.action === "trade").length;

  return (
    <Page className="gap-10">
      <PageTitle aside={cycles.length ? `${trades} traded, ${cycles.length - trades} held or rejected` : null}>
        Decisions
      </PageTitle>

      {cycles.length === 0 ? (
        <Quiet>No decisions yet. The first research session will add one.</Quiet>
      ) : (
        <ul className="flex flex-col">
          {cycles.map((c) => (
            <li key={c.cycle_key} className="border-t">
              <Link
                href={cycleHref(c.cycle_key, fund.fund_id)}
                className="-mx-3 grid grid-cols-[4.5rem_1fr_auto] gap-x-5 gap-y-1 rounded-md px-3 py-4 hover:bg-wash sm:grid-cols-[4.5rem_4.5rem_1fr_auto]"
              >
                <span className="text-sm text-graphite">{formatDay(c.as_of)}</span>
                <span className="hidden text-sm text-graphite sm:block">{actionLabel(c.action)}</span>
                <span className="line-clamp-2 max-w-[68ch]">{c.thesis || "No reasoning recorded."}</span>
                <span className="text-right text-sm">
                  {c.nav != null ? formatUsd(c.nav) : "—"}
                  {c.fill_count > 0 ? (
                    <span className="block text-graphite">
                      {c.fill_count} {c.fill_count === 1 ? "fill" : "fills"}
                    </span>
                  ) : null}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Page>
  );
}
