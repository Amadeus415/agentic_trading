import Link from "next/link";
import { notFound } from "next/navigation";

import {
  actionLabel,
  beliefLine,
  capitalize,
  contractName,
  contractOutcome,
  contractTitles,
  cycleHref,
} from "@/components/display";
import { formatPct, formatPrice, formatQty, formatTs, formatUsd } from "@/components/format";
import { Fact, Facts, FundEmpty, List, Money, Note, Page, Section, TableWrap } from "@/components/panel";
import { getCycle, getSelectedFund, type FundSearchParams, listCycles } from "@/lib/fund";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export default async function CycleDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ cycleKey: string }>;
  searchParams: FundSearchParams;
}) {
  const { cycleKey: rawKey } = await params;
  const cycleKey = decodeURIComponent(rawKey);
  const fund = await getSelectedFund(searchParams);
  if (!fund) return <FundEmpty />;

  const cycle = getCycle(fund.fund_id, cycleKey);
  if (!cycle) notFound();

  const all = listCycles(fund.fund_id);
  const index = all.findIndex((c) => c.cycle_key === cycle.cycle_key);
  const prev = index > 0 ? all[index - 1] : null;
  const next = index >= 0 && index < all.length - 1 ? all[index + 1] : null;
  const titles = contractTitles(all.slice(0, index + 1));
  const name = (id: string, asset?: string) => contractName(titles, id, asset ?? (contractOutcome(id) ? "prediction" : undefined));
  const fills = [...cycle.fills, ...cycle.settlements];
  const journal = cycle.journal;
  const hypotheses = journal?.hypotheses ?? [];
  const risk = cycle.audit?.risk ?? null;
  const failed = risk?.checks.filter((check) => !check.passed) ?? [];
  const runtimeInfo = cycle.audit?.runtime ?? null;

  return (
    <Page>
      <header className="flex flex-col gap-6">
        <div className="flex flex-wrap items-center justify-between gap-4 text-sm text-graphite">
          <Link href={`/cycles?fund=${encodeURIComponent(fund.fund_id)}`} className="hover:text-ink">
            All decisions
          </Link>
          <div className="flex gap-5">
            {prev ? (
              <Link href={cycleHref(prev.cycle_key, fund.fund_id)} className="hover:text-ink">
                Previous
              </Link>
            ) : null}
            {next ? (
              <Link href={cycleHref(next.cycle_key, fund.fund_id)} className="hover:text-ink">
                Next
              </Link>
            ) : null}
          </div>
        </div>
        <div>
          <h1 className="text-[32px] leading-tight font-light tracking-[-0.02em]">
            {actionLabel(cycle.action)} on {formatTs(cycle.as_of)}
          </h1>
          <p className="mt-6 max-w-[64ch] text-[19px] leading-[1.65] font-light">{cycle.thesis || "No reasoning recorded."}</p>
        </div>
        <Facts>
          <Fact label="Fund value after">{formatUsd(cycle.state.nav)}</Fact>
          <Fact label="Cash">{formatUsd(cycle.state.cash)}</Fact>
          <Fact label="Fills">{fills.length}</Fact>
          <Fact label="Fees">{formatUsd(cycle.audit?.fee_total ?? "0")}</Fact>
        </Facts>
      </header>

      <Section title="Reasoning">
        <dl className="flex flex-col">
          <Note label="What changed">{journal?.what_changed}</Note>
          <Note label="The market">{journal?.market_regime}</Note>
          <Note label="Opportunities">{journal?.opportunity_set}</Note>
          <Note label="Intent">{journal?.portfolio_intent}</Note>
          <Note label="Risks">{cycle.risks}</Note>
          <Note label="Alternatives">{cycle.alternatives}</Note>
          <Note label="Lessons applied">{journal?.lessons_applied.length ? <List items={journal.lessons_applied} /> : null}</Note>
        </dl>
        {!journal ? <p className="text-graphite">This early decision has no written journal.</p> : null}
      </Section>

      {hypotheses.length > 0 ? (
        <Section title="Forecasts" aside={`${hypotheses.length} contracts`}>
          <ul className="flex flex-col">
            {hypotheses.map((h) => (
              <li key={h.instrument_id} className="border-t">
                <details className="group">
                  <summary className="-mx-3 grid grid-cols-[1fr_auto] gap-x-6 gap-y-0.5 rounded-md px-3 py-4 hover:bg-wash">
                    <span className="min-w-0">{name(h.instrument_id)}</span>
                    <span>{formatPct(h.p_win ?? h.confidence)} chance</span>
                    <span className="col-span-2 text-sm text-graphite">{beliefLine(h)}</span>
                  </summary>
                  <dl className="flex flex-col pb-4 sm:pl-0">
                    <Note label="Claim">{h.statement}</Note>
                    <Note label="Why">{h.mechanism}</Note>
                    <Note label="Catalysts">{h.catalysts.length ? <List items={h.catalysts} /> : null}</Note>
                    <Note label="Proves it wrong">{h.falsifiers.length ? <List items={h.falsifiers} /> : null}</Note>
                    <Note label="Sources">{h.evidence_ids.join(", ")}</Note>
                  </dl>
                </details>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {cycle.orders.length > 0 ? (
        <Section title="Orders">
          <TableWrap>
            <table className="ledger">
              <thead>
                <tr>
                  <th>Contract</th>
                  <th>Side</th>
                  <th className="num">Quantity</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {cycle.orders.map((order, i) => (
                  <tr key={`${order.instrument_id}:${order.side}:${i}`}>
                    <td className="min-w-48">{name(order.instrument_id, order.asset_class)}</td>
                    <td>{capitalize(order.side)}</td>
                    <td className="num">{formatQty(order.quantity)}</td>
                    <td className="min-w-72 text-graphite">{order.rationale}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </Section>
      ) : null}

      {fills.length > 0 ? (
        <Section title="Fills">
          <TableWrap>
            <table className="ledger">
              <thead>
                <tr>
                  <th>Contract</th>
                  <th>Side</th>
                  <th className="num">Quantity</th>
                  <th className="num">Price</th>
                  <th className="num">Cost</th>
                  <th className="num">Fee</th>
                  <th className="num">Realized</th>
                </tr>
              </thead>
              <tbody>
                {fills.map((fill) => (
                  <tr key={fill.fill_id}>
                    <td className="min-w-48">{name(fill.instrument_id, fill.asset_class)}</td>
                    <td>{capitalize(fill.side)}</td>
                    <td className="num">{formatQty(fill.quantity)}</td>
                    <td className="num">{formatPrice(fill.execution_price, fill.asset_class)}</td>
                    <td className="num">{formatUsd(fill.gross_notional)}</td>
                    <td className="num text-graphite">{formatUsd(fill.fee)}</td>
                    <td className="num"><Money value={fill.realized_pnl} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </Section>
      ) : null}

      {cycle.evidence.length > 0 ? (
        <Section title="Sources" aside={`${cycle.evidence.length} cited`}>
          <ul className="flex flex-col">
            {cycle.evidence.map((item) => (
              <li key={item.evidence_id} className="grid gap-1 border-t py-4 sm:grid-cols-[1fr_12rem] sm:gap-8">
                <p className="max-w-[68ch]">{item.claim}</p>
                <p className="text-sm text-graphite sm:text-right">
                  {item.source_url ? (
                    <a href={item.source_url} target="_blank" rel="noreferrer" className="text-fund hover:underline">
                      {item.source_name || "Source"}
                    </a>
                  ) : (
                    item.source_name
                  )}
                  <span className="block">{formatTs(item.observed_at)}</span>
                </p>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {risk || runtimeInfo ? (
        <Section title="Checks">
          <div className="flex flex-col border-t">
            {risk ? (
              <details className="border-b">
                <summary className="-mx-3 flex justify-between gap-6 rounded-md px-3 py-4 hover:bg-wash">
                  <span>
                    {failed.length === 0
                      ? `All ${risk.checks.length} risk checks passed`
                      : `${failed.length} of ${risk.checks.length} risk checks failed`}
                  </span>
                  <span className="text-sm text-graphite">Show</span>
                </summary>
                <TableWrap>
                  <table className="ledger mb-4">
                    <thead>
                      <tr>
                        <th>Check</th>
                        <th className="num">Observed</th>
                        <th className="num">Limit</th>
                        <th className="num">Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {risk.checks.map((check) => (
                        <tr key={check.name}>
                          <td>{capitalize(check.name.replaceAll("_", " "))}</td>
                          <td className="num">{check.observed}</td>
                          <td className="num text-graphite">{check.limit ?? "—"}</td>
                          <td className={check.passed ? "num text-graphite" : "num text-loss"}>{check.passed ? "Passed" : "Failed"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              </details>
            ) : null}
            {runtimeInfo ? (
              <details className="border-b">
                <summary className="-mx-3 flex justify-between gap-6 rounded-md px-3 py-4 hover:bg-wash">
                  <span>Researched by {runtimeInfo.model ?? "an unrecorded model"}</span>
                  <span className="text-sm text-graphite">Show</span>
                </summary>
                <dl className="grid grid-cols-[8rem_1fr] gap-x-6 gap-y-2 pb-5 text-sm">
                  <dt className="text-graphite">Version</dt>
                  <dd className="break-all">{runtimeInfo.edgecraft_version}</dd>
                  <dt className="text-graphite">Prompt</dt>
                  <dd className="break-all">{runtimeInfo.prompt_version ?? "—"}</dd>
                  <dt className="text-graphite">Input</dt>
                  <dd className="break-all">{runtimeInfo.input_sha256 ?? "—"}</dd>
                  <dt className="text-graphite">Request</dt>
                  <dd className="break-all">{cycle.request_digest}</dd>
                  <dt className="text-graphite">Key</dt>
                  <dd className="break-all">{cycle.cycle_key}</dd>
                </dl>
              </details>
            ) : null}
          </div>
        </Section>
      ) : null}
    </Page>
  );
}
