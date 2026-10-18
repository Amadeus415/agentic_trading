import { formatPct, formatUsd } from "@/components/format";
import { FundEmpty, Panel } from "@/components/panel";
import { StatCard } from "@/components/stat-card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getSelectedFund, type FundSearchParams } from "@/lib/fund";
import { readFundReport, type ForecastSkill } from "@/lib/report";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export default async function AttributionPage({ searchParams }: { searchParams: FundSearchParams }) {
  const fund = await getSelectedFund(searchParams);
  const report = fund ? readFundReport(fund.fund_id) : null;
  if (!report) {
    return (
      <FundEmpty
        title="No attribution report found"
        detail="Run make fund-report-file, then refresh this page."
      />
    );
  }

  const summary = report.summary;
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
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Closed round trips" value={String(summary.closed_trades)} />
        <StatCard label="Hit rate" value={summary.hit_rate == null ? "—" : formatPct(Number(summary.hit_rate))} />
        <StatCard
          label="Expectancy"
          value={summary.expectancy_after_cost == null ? "—" : formatUsd(Number(summary.expectancy_after_cost))}
        />
        <StatCard
          label="Profit factor"
          value={summary.profit_factor === "Infinity" ? "∞" : summary.profit_factor == null ? "—" : Number(summary.profit_factor).toFixed(2)}
        />
      </section>

      {report.prediction_scores && <Panel micro="FORECASTS" title="Does the model beat the market?" bodyClassName="space-y-3 p-3.5">
        <p className="text-xs text-muted-foreground">{report.prediction_scores.interpretation}</p>
        <div className="grid gap-3 sm:grid-cols-3">
          <StatCard label={`Brier improvement · n=${report.prediction_scores.summary.model_brier_count}`} value={report.prediction_scores.summary.brier_improvement == null ? "—" : Number(report.prediction_scores.summary.brier_improvement).toFixed(4)} />
          <StatCard label={`Sampled CLV · n=${report.prediction_scores.summary.sampled_clv_count}`} value={report.prediction_scores.summary.sampled_clv == null ? "—" : Number(report.prediction_scores.summary.sampled_clv).toFixed(4)} />
          <StatCard label="Unique funded contracts" value={String(report.prediction_scores.summary.contracts)} />
        </div>
      </Panel>}
      {report.forecast_skill && <ForecastTrust skill={report.forecast_skill} />}
      {report.lineage && <Panel micro="PROVENANCE" title="Performance by code revision" bodyClassName="space-y-3 p-3.5">
        <p className="text-xs text-muted-foreground">NAV changes include marks on earlier positions. This timeline does not establish that a code change caused a return. Historical revisions are labelled inferred.</p>
        <Table><TableHeader><TableRow><TableHead>Revision / why</TableHead><TableHead>Basis</TableHead><TableHead>Cycles</TableHead><TableHead>NAV change</TableHead><TableHead>Fees</TableHead></TableRow></TableHeader>
          <TableBody>{report.lineage.segments.map((segment, index) => <TableRow key={`${segment.revision}-${index}`}>
            <TableCell><p className="font-mono">{segment.revision.slice(0, 12)}{segment.revision.endsWith("+dirty") ? "+dirty" : ""}</p><p className="text-xs text-muted-foreground">{segment.commit}</p></TableCell>
            <TableCell>{segment.basis}</TableCell><TableCell>{segment.cycles}</TableCell><TableCell>{formatUsd(Number(segment.nav_change))}</TableCell><TableCell>{formatUsd(Number(segment.fees))}</TableCell>
          </TableRow>)}</TableBody>
        </Table>
      </Panel>}
      <Panel micro="BELIEFS" title="Calibration" bodyClassName="space-y-3 p-3.5">
        <p className="text-xs text-muted-foreground">
          Stated p_win buckets versus resolved outcomes. Sparse marks remain unscored.
        </p>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Bucket</TableHead>
              <TableHead className="text-right">n</TableHead>
              <TableHead className="text-right">Stated</TableHead>
              <TableHead className="text-right">Realized</TableHead>
              <TableHead className="text-right">Error</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {report.calibration.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  No resolved beliefs yet.
                </TableCell>
              </TableRow>
            ) : (
              report.calibration.map((row) => (
                <TableRow key={row.bucket}>
                  <TableCell className="font-mono">{row.bucket}</TableCell>
                  <TableCell className="text-right font-mono">{row.count}</TableCell>
                  <TableCell className="text-right font-mono">
                    {formatPct(Number(row.mean_stated_p_win))}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {formatPct(Number(row.realized_win_rate))}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {formatPct(Number(row.calibration_error))}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Panel>

      <Panel micro="LEARNING" title="Strategy changes" bodyClassName="space-y-3 p-3.5">
        <p className="text-xs text-muted-foreground">
          {report.review?.completed_reviews ?? 0} completed reviews. Experiments use separate IDs;
          shadow experiments receive no trading capital. Status alone is not proof of improvement.
        </p>
        {Object.entries(report.playbook_statuses ?? {}).map(([id, status]) => (
          <p key={id} className="text-xs"><span className="font-mono">{id}</span> · {status}</p>
        ))}
      </Panel>

      <Panel micro="SLEEVES" title="Playbook results" bodyClassName="space-y-3 p-3.5">
        <p className="text-xs text-muted-foreground">
          After-cost round trips grouped by the opening playbook.
        </p>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Playbook</TableHead>
              <TableHead className="text-right">Trades</TableHead>
              <TableHead className="text-right">Hit rate</TableHead>
              <TableHead className="text-right">Expectancy</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {[...byPlaybook.entries()].map(([playbook, row]) => (
              <TableRow key={playbook}>
                <TableCell className="font-mono">{playbook}</TableCell>
                <TableCell className="text-right font-mono">{row.count}</TableCell>
                <TableCell className="text-right font-mono">
                  {formatPct(row.count ? row.wins / row.count : 0)}
                </TableCell>
                <TableCell className="text-right font-mono">
                  {formatUsd(row.count ? row.pnl / row.count : 0)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Panel>

      <Panel micro="TRADES" title="After-cost attribution" bodyClassName="space-y-3 p-3.5">
        <p className="text-xs text-muted-foreground">
          {summary.hypotheses} journaled beliefs are retained for calibration. Python allocates
          each opening fee exactly once.
        </p>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Instrument</TableHead>
              <TableHead>Side</TableHead>
              <TableHead>Playbook</TableHead>
              <TableHead>Closed</TableHead>
              <TableHead className="text-right">After-cost P&amp;L</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {[...report.round_trips].reverse().map((trip, index) => (
              <TableRow key={`${trip.instrument_id}-${trip.closed_at}-${index}`}>
                <TableCell className="font-mono">{trip.instrument_id}</TableCell>
                <TableCell>{trip.side}</TableCell>
                <TableCell className="font-mono">{trip.playbook_id}</TableCell>
                <TableCell>{new Date(trip.closed_at).toLocaleString()}</TableCell>
                <TableCell className="text-right font-mono">
                  {formatUsd(Number(trip.realized_pnl_after_cost))}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Panel>

      <p className="text-xs text-muted-foreground">
        Canonical report generated {new Date(report.generated_at).toLocaleString()} by
        edgecraft fund-report.
      </p>
    </div>
  );
}

function fixed(value: number | null, digits = 4) {
  return value == null ? "—" : value.toFixed(digits);
}

function ForecastTrust({ skill }: { skill: ForecastSkill }) {
  const rows = Object.entries(skill.variants);
  const bias = skill.favorite_bias;
  return (
    <Panel micro="TRUST" title="How much sizing trusts each playbook" bodyClassName="space-y-3 p-3.5">
      <p className="text-xs text-muted-foreground">{skill.interpretation}</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Research forecasts" value={String(skill.summary.forecasts)} />
        <StatCard label={`Skill vs market · n=${skill.summary.resolved}`} value={fixed(skill.summary.skill)} />
        <StatCard
          label={`Favorite-bias γ · ${bias.resolved} settled of ${bias.observed}`}
          value={bias.fitted_gamma == null ? `${bias.gamma.toFixed(2)} (prior)` : bias.gamma.toFixed(2)}
        />
      </div>
      {rows.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Playbook</TableHead>
              <TableHead className="text-right">Forecasts</TableHead>
              <TableHead className="text-right">Resolved</TableHead>
              <TableHead className="text-right">Skill</TableHead>
              <TableHead className="text-right">Drift</TableHead>
              <TableHead className="text-right">Trust</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(([name, row]) => (
              <TableRow key={name}>
                <TableCell className="font-mono text-xs">{name}</TableCell>
                <TableCell className="text-right tabular-nums">{row.forecasts}</TableCell>
                <TableCell className="text-right tabular-nums">{row.resolved}</TableCell>
                <TableCell className="text-right tabular-nums">{fixed(row.skill)}</TableCell>
                <TableCell className="text-right tabular-nums">{fixed(row.mean_drift_toward_forecast)}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.trust.toFixed(2)} <span className="text-muted-foreground">({row.trust_basis})</span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {skill.head_to_head.map((match) => (
        <p key={`${match.left}-${match.right}`} className="text-xs text-muted-foreground">
          {match.left_advantage >= 0 ? match.left : match.right} beat{" "}
          {match.left_advantage >= 0 ? match.right : match.left} by {Math.abs(match.left_advantage).toFixed(4)} Brier on{" "}
          {match.shared_resolved} shared contracts.
        </p>
      ))}
    </Panel>
  );
}
