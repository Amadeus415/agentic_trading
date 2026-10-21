/**
 * One contract: what the fund holds or held, why, and every trade in it.
 */
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  beliefLine,
  capitalize,
  contractName,
  contractTitles,
  cycleHref,
  holdingDetail,
  num,
  openPositions,
} from "@/components/display";
import { formatDay, formatPct, formatPrice, formatQty, formatUsd } from "@/components/format";
import { Fact, Facts, FundEmpty, List, Money, Note, Page, Section, TableWrap } from "@/components/panel";
import {
  closedPositions,
  extractFillsFromCycles,
  getLatestState,
  getSelectedFund,
  latestHypothesesByInstrument,
  listCycles,
  type FundSearchParams,
} from "@/lib/fund";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export default async function PositionPage({
  params,
  searchParams,
}: {
  params: Promise<{ instrumentId: string }>;
  searchParams: FundSearchParams;
}) {
  const { instrumentId: rawId } = await params;
  const instrumentId = decodeURIComponent(rawId);
  const fund = await getSelectedFund(searchParams);
  if (!fund) return <FundEmpty />;

  const cycles = listCycles(fund.fund_id);
  const positions = openPositions(getLatestState(fund.fund_id)?.positions ?? []);
  const trades = extractFillsFromCycles(cycles).filter((t) => t.instrument_id === instrumentId);
  const open = positions.find((p) => p.instrument_id === instrumentId) ?? null;
  if (!open && trades.length === 0) notFound();

  const closed = open ? null : closedPositions(trades, positions)[0] ?? null;
  const assetClass = open?.asset_class ?? trades[0]?.asset_class;
  const hypothesis = latestHypothesesByInstrument(cycles).get(instrumentId) ?? null;
  const fees = trades.reduce((sum, t) => sum + num(t.fee), 0);
  const query = `?fund=${encodeURIComponent(fund.fund_id)}`;

  return (
    <Page>
      <header className="flex flex-col gap-6">
        <Link href={`/${query}`} className="self-start text-sm text-graphite hover:text-ink">
          Overview
        </Link>
        <div>
          <h1 className="text-[32px] leading-tight font-light tracking-[-0.02em]">
            {contractName(contractTitles(cycles), instrumentId, assetClass)}
          </h1>
          <p className="mt-3 text-[17px] font-light text-graphite">
            {open ? holdingDetail(open) : `Closed ${formatDay(closed?.closed_at)}`}
          </p>
        </div>
        {open ? (
          <Facts>
            <Fact label="Value">{formatUsd(open.market_value)}</Fact>
            <Fact label="Gain or loss">
              <Money value={open.unrealized_pnl} />
            </Fact>
            <Fact label="Paid">{formatPrice(open.average_entry, open.asset_class)}</Fact>
            <Fact label="Now">{formatPrice(open.mark_price, open.asset_class)}</Fact>
          </Facts>
        ) : (
          <Facts>
            <Fact label="Result after fees">
              <Money value={closed?.result} />
            </Fact>
            <Fact label="Trades">{trades.length}</Fact>
            <Fact label="Fees">{formatUsd(fees)}</Fact>
            <Fact label="Closed">{formatDay(closed?.closed_at)}</Fact>
          </Facts>
        )}
      </header>

      {hypothesis ? (
        <Section title="Forecast" aside={`${formatPct(hypothesis.p_win ?? hypothesis.confidence)} chance`}>
          <dl className="flex flex-col">
            <Note label="Claim">{hypothesis.statement}</Note>
            <Note label="Why">{hypothesis.mechanism}</Note>
            <Note label="Plan">{beliefLine(hypothesis)}</Note>
            <Note label="Catalysts">{hypothesis.catalysts.length ? <List items={hypothesis.catalysts} /> : null}</Note>
            <Note label="Proves it wrong">
              {hypothesis.falsifiers.length ? <List items={hypothesis.falsifiers} /> : null}
            </Note>
          </dl>
        </Section>
      ) : null}

      {trades.length > 0 ? (
        <Section title="Trades" aside={`${formatUsd(fees)} in fees`}>
          <TableWrap>
            <table className="ledger">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Side</th>
                  <th className="num">Quantity</th>
                  <th className="num">Price</th>
                  <th className="num">Fee</th>
                  <th className="num">Cash</th>
                </tr>
              </thead>
              <tbody>
                {[...trades].reverse().map((t) => (
                  <tr key={t.fill_id}>
                    <td className="whitespace-nowrap">
                      <Link href={cycleHref(t.cycle_key, fund.fund_id)} className="text-fund hover:underline">
                        {formatDay(t.as_of)}
                      </Link>
                    </td>
                    <td>{capitalize(t.side)}</td>
                    <td className="num">{formatQty(t.quantity)}</td>
                    <td className="num">{formatPrice(t.execution_price, t.asset_class)}</td>
                    <td className="num text-graphite">{formatUsd(t.fee)}</td>
                    <td className="num">
                      <Money value={t.cash_delta} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </Section>
      ) : null}
    </Page>
  );
}
