import type { ReactNode } from "react";

import { capitalize } from "@/components/display";
import { formatDay, formatPct, formatTs, formatUsd } from "@/components/format";
import { Fact, Facts, FundEmpty, Money, Page, PageTitle, Quiet, Section, TableWrap } from "@/components/panel";
import { getSelectedFund, type FundSearchParams } from "@/lib/fund";
import { readFundReport } from "@/lib/report";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function score(value: number | string | null | undefined, digits = 4): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(digits)}`;
}

/** Python's own explanation, one click away instead of always on screen. */
function HowToRead({ children }: { children: ReactNode }) {
  return (
    <details className="text-sm text-graphite">
      <summary className="hover:text-ink">How to read this</summary>
      <p className="mt-2 max-w-[72ch] leading-[1.7]">{children}</p>
    </details>
  );
}

export default async function AttributionPage({ searchParams }: { searchParams: FundSearchParams }) {
  const fund = await getSelectedFund(searchParams);
  const report = fund ? readFundReport(fund.fund_id) : null;
  if (!report) return <FundEmpty title="No scorecard yet" detail="Run make fund-report-file, then refresh." />;

  const { summary, review } = report;
  const scores = report.prediction_scores;
  const skill = report.forecast_skill;
  const statuses = report.playbook_statuses ?? {};
  const playbooks = [...new Set([...Object.keys(skill?.variants ?? {}), ...Object.keys(statuses)])];

  const byPlaybook = new Map<string, { pnl: number; count: number; wins: number }>();
  for (const trip of report.round_trips) {
    const row = byPlaybook.get(trip.playbook_id) ?? { pnl: 0, count: 0, wins: 0 };
    const pnl = Number(trip.realized_pnl_after_cost);
    row.pnl += pnl;
    row.count += 1;
    if (pnl > 0) row.wins += 1;
    byPlaybook.set(trip.playbook_id, row);
  }

  return (
    <Page>
      <section className="flex flex-col gap-10">
        <PageTitle aside={`Updated ${formatTs(report.generated_at)}`}>Scorecard</PageTitle>
        <Facts>
          <Fact label="Closed trades">{summary.closed_trades}</Fact>
          <Fact label="Win rate">{summary.hit_rate == null ? "—" : formatPct(summary.hit_rate)}</Fact>
          <Fact label="Average after costs">
            {summary.expectancy_after_cost == null ? "—" : <Money value={summary.expectancy_after_cost} />}
          </Fact>
          <Fact label="Profit factor">
            {summary.profit_factor === "Infinity" ? "∞" : summary.profit_factor == null ? "—" : Number(summary.profit_factor).toFixed(2)}
          </Fact>
        </Facts>
        {review ? (
          <p className="text-graphite">
            {review.due
              ? "A strategy review is due now."
              : `Next strategy review ${formatDay(review.next_review_at)}, or sooner after ${review.trade_threshold} closed trades (${review.closed_trades_since_review} so far).`}{" "}
            {review.completed_reviews} {review.completed_reviews === 1 ? "review" : "reviews"} done.
          </p>
        ) : null}
      </section>

      {scores || skill ? (
        <Section title="Forecasts against the market">
          <Facts>
            {skill ? (
              <Fact label={`Skill, ${skill.summary.resolved} resolved`}>{score(skill.summary.skill)}</Fact>
            ) : null}
            {scores ? (
              <Fact label={`Brier gain, ${scores.summary.model_brier_count} scored`}>{score(scores.summary.brier_improvement)}</Fact>
            ) : null}
            {scores ? (
              <Fact label={`Price drift, ${scores.summary.sampled_clv_count} sampled`}>{score(scores.summary.sampled_clv)}</Fact>
            ) : null}
            {skill ? <Fact label="Forecasts made">{skill.summary.forecasts}</Fact> : null}
          </Facts>
          <HowToRead>
            {[scores?.interpretation, skill?.interpretation].filter(Boolean).join(" ")}
          </HowToRead>
        </Section>
      ) : null}

      {playbooks.length > 0 ? (
        <Section title="Playbooks">
          <TableWrap>
            <table className="ledger">
              <thead>
                <tr>
                  <th>Playbook</th>
                  <th>Status</th>
                  <th className="num">Forecasts</th>
                  <th className="num">Resolved</th>
                  <th className="num">Skill</th>
                  <th className="num">Trust</th>
                  <th className="num">Closed</th>
                  <th className="num">Average</th>
                </tr>
              </thead>
              <tbody>
                {playbooks.map((id) => {
                  const variant = skill?.variants[id];
                  const results = byPlaybook.get(id);
                  return (
                    <tr key={id}>
                      <td className="break-all">{id}</td>
                      <td className="text-graphite">{statuses[id] ? capitalize(statuses[id]) : "—"}</td>
                      <td className="num">{variant?.forecasts ?? "—"}</td>
                      <td className="num">{variant?.resolved ?? "—"}</td>
                      <td className="num">{variant ? score(variant.skill) : "—"}</td>
                      <td className="num">{variant ? variant.trust.toFixed(2) : "—"}</td>
                      <td className="num">{results?.count ?? 0}</td>
                      <td className="num">{results ? <Money value={results.pnl / results.count} /> : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
          {skill ? (
            <div className="flex flex-col gap-1 text-sm text-graphite">
              <p>
                Favorites settle {skill.favorite_bias.gamma > 1 ? "more" : "less"} often than priced (γ {skill.favorite_bias.gamma.toFixed(2)}
                {skill.favorite_bias.fitted_gamma == null ? ", still the prior" : `, from ${skill.favorite_bias.resolved} settled`}).
              </p>
              {skill.head_to_head.map((match) => (
                <p key={`${match.left}-${match.right}`}>
                  {match.left_advantage >= 0 ? match.left : match.right} beat {match.left_advantage >= 0 ? match.right : match.left} by{" "}
                  {Math.abs(match.left_advantage).toFixed(4)} Brier on {match.shared_resolved} shared contracts.
                </p>
              ))}
            </div>
          ) : null}
        </Section>
      ) : null}

      <Section title="Calibration" aside="Said versus happened">
        {report.calibration.length === 0 ? (
          <Quiet>Nothing has resolved yet.</Quiet>
        ) : (
          <TableWrap>
            <table className="ledger">
              <thead>
                <tr>
                  <th>Confidence</th>
                  <th className="num">Count</th>
                  <th className="num">Said</th>
                  <th className="num">Happened</th>
                  <th className="num">Off by</th>
                </tr>
              </thead>
              <tbody>
                {report.calibration.map((row) => (
                  <tr key={row.bucket}>
                    <td>{row.bucket}</td>
                    <td className="num">{row.count}</td>
                    <td className="num">{formatPct(row.mean_stated_p_win)}</td>
                    <td className="num">{formatPct(row.realized_win_rate)}</td>
                    <td className="num text-graphite">{formatPct(row.calibration_error)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Section>

      <Section title="Closed trades" aside={report.round_trips.length ? `${summary.hypotheses} forecasts on record` : null}>
        {report.round_trips.length === 0 ? (
          <Quiet>No trades have closed yet.</Quiet>
        ) : (
          <TableWrap>
            <table className="ledger">
              <thead>
                <tr>
                  <th>Closed</th>
                  <th>Contract</th>
                  <th>Side</th>
                  <th>Playbook</th>
                  <th className="num">After costs</th>
                </tr>
              </thead>
              <tbody>
                {[...report.round_trips].reverse().map((trip, index) => (
                  <tr key={`${trip.instrument_id}-${trip.closed_at}-${index}`}>
                    <td className="whitespace-nowrap text-graphite">{formatDay(trip.closed_at)}</td>
                    <td className="break-all">{trip.instrument_id}</td>
                    <td>{capitalize(trip.side)}</td>
                    <td className="break-all text-graphite">{trip.playbook_id}</td>
                    <td className="num"><Money value={trip.realized_pnl_after_cost} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Section>

      {report.lineage?.segments.length ? (
        <Section title="By code version">
          <TableWrap>
            <table className="ledger">
              <thead>
                <tr>
                  <th>Change</th>
                  <th className="num">Decisions</th>
                  <th className="num">Fund value</th>
                  <th className="num">Fees</th>
                </tr>
              </thead>
              <tbody>
                {report.lineage.segments.map((segment, index) => (
                  <tr key={`${segment.revision}-${index}`}>
                    <td className="min-w-72">
                      {segment.commit}
                      <span className="block text-sm text-graphite">
                        {segment.revision.slice(0, 7)}
                        {segment.revision.endsWith("+dirty") ? " with local edits" : ""}
                        {segment.basis !== "recorded" ? `, ${segment.basis}` : ""}
                      </span>
                    </td>
                    <td className="num">{segment.cycles}</td>
                    <td className="num"><Money value={segment.nav_change} /></td>
                    <td className="num text-graphite">{formatUsd(segment.fees)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
          <p className="text-sm text-graphite">Value changes include marks on older positions, so they don’t prove a change caused a return.</p>
        </Section>
      ) : null}
    </Page>
  );
}
