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
import { readFundReport } from "@/lib/report";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export default function AttributionPage() {
  const report = readFundReport();
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
