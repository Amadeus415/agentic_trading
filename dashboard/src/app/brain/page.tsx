import Link from "next/link";

import { actionLabel, contractName, contractTitles, cycleHref } from "@/components/display";
import { formatDay, formatPct, formatQty } from "@/components/format";
import { Fact, Facts, FundEmpty, Money, Page, PageTitle, Quiet, Section, TableWrap } from "@/components/panel";
import { fundBrain, getLatestState, getSelectedFund, listCycles, listEvents, type FundSearchParams } from "@/lib/fund";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export default async function BrainPage({ searchParams }: { searchParams: FundSearchParams }) {
  const fund = await getSelectedFund(searchParams);
  if (!fund) return <FundEmpty />;

  const cycles = listCycles(fund.fund_id);
  const state = getLatestState(fund.fund_id);
  if (!state) return <FundEmpty title="Nothing remembered yet" detail="Memory starts after the first decision." />;

  const brain = fundBrain(fund.fund_id, state, cycles, listEvents(fund.fund_id));
  const titles = contractTitles(cycles);
  const { activity } = brain;
  const traded = brain.instruments.filter((item) => item.simulated_fill_count > 0 || Number(item.current_quantity) !== 0);

  return (
    <Page>
      <section className="flex flex-col gap-10">
        <PageTitle>Memory</PageTitle>
        <Facts>
          <Fact label="In cash">{formatPct(activity.cash_nav_weight)}</Fact>
          <Fact label="Open positions">{activity.open_position_count}</Fact>
          <Fact label="Recent trading decisions">{activity.recent_trade_cycles}</Fact>
          <Fact label="All-cash holds in a row">{activity.consecutive_all_cash_holds}</Fact>
        </Facts>
        <details className="text-sm text-graphite">
          <summary className="hover:text-ink">What the next session sees</summary>
          <p className="mt-2 max-w-[72ch] leading-[1.7]">{brain.learning_boundary}</p>
        </details>
      </section>

      <Section title="Notes for the next session">
        {brain.adaptive_prompts.length === 0 ? (
          <Quiet>No notes yet.</Quiet>
        ) : (
          <ul className="flex flex-col">
            {brain.adaptive_prompts.map((prompt) => (
              <li key={prompt} className="border-t py-4 leading-[1.7]">
                <p className="max-w-[72ch]">{prompt}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="What happened next" aside="The next decision’s change in fund value">
        {brain.recent_cycles.length === 0 ? (
          <Quiet>No decisions yet.</Quiet>
        ) : (
          <TableWrap>
            <table className="ledger">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Decision</th>
                  <th>What changed</th>
                  <th className="num">Next</th>
                </tr>
              </thead>
              <tbody>
                {[...brain.recent_cycles].reverse().map((item) => (
                  <tr key={item.cycle_key}>
                    <td className="whitespace-nowrap">
                      <Link href={cycleHref(item.cycle_key, fund.fund_id)} className="text-fund hover:underline">
                        {formatDay(item.as_of)}
                      </Link>
                    </td>
                    <td className="text-graphite">{actionLabel(item.action)}</td>
                    <td className="min-w-72">
                      <span className="line-clamp-2">{item.what_changed || item.thesis}</span>
                    </td>
                    <td className="num">
                      {item.next_cycle_nav_change != null ? (
                        <Money value={item.next_cycle_nav_change} />
                      ) : (
                        <span className="text-graphite">Pending</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Section>

      <Section title="Contracts" aside={traded.length ? `${traded.length} traded` : null}>
        {traded.length === 0 ? (
          <Quiet>Nothing traded yet.</Quiet>
        ) : (
          <TableWrap>
            <table className="ledger">
              <thead>
                <tr>
                  <th>Contract</th>
                  <th className="num">Holding</th>
                  <th className="num">Open</th>
                  <th className="num">Realized</th>
                  <th className="num">Wins / losses</th>
                </tr>
              </thead>
              <tbody>
                {traded.map((item) => (
                  <tr key={item.instrument_id}>
                    <td className="min-w-56">{contractName(titles, item.instrument_id, item.asset_class)}</td>
                    <td className="num">{Number(item.current_quantity) === 0 ? "—" : formatQty(item.current_quantity)}</td>
                    <td className="num">{item.current_unrealized_pnl != null ? <Money value={item.current_unrealized_pnl} /> : "—"}</td>
                    <td className="num"><Money value={item.realized_pnl} /></td>
                    <td className="num">
                      {item.profitable_exit_count} / {item.losing_exit_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Section>

      {brain.recent_rejections.length > 0 ? (
        <Section title="Rejected">
          <ul className="flex flex-col">
            {brain.recent_rejections.map((item, i) => (
              <li key={`${item.cycle_key ?? "none"}:${i}`} className="grid gap-1 border-t py-4 sm:grid-cols-[12rem_1fr] sm:gap-8">
                <span className="text-sm text-loss">{item.error_type}</span>
                <span className="max-w-[68ch] text-graphite">{item.reason}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </Page>
  );
}
