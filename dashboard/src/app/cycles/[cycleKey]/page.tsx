import Link from "next/link";
import { notFound } from "next/navigation";

import {
  actionBadgeClass,
  cycleHref,
  num,
  pnlClass,
  sideBadgeClass,
  truncateId,
} from "@/components/display";
import {
  formatQty,
  formatTs,
  formatUsd,
} from "@/components/format";
import { HypothesisTable } from "@/components/hypothesis-table";
import { FundEmpty, Panel } from "@/components/panel";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getCycle, getDefaultFund, listCycles } from "@/lib/fund";
import { cn } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function JournalBlock({
  label,
  children,
}: {
  label: string;
  children: string;
}) {
  if (!children) return null;
  return (
    <div>
      <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
        {label}
      </p>
      <p className="mt-1 text-sm leading-relaxed text-foreground">{children}</p>
    </div>
  );
}

export default async function CycleDetailPage({
  params,
}: {
  params: Promise<{ cycleKey: string }>;
}) {
  const { cycleKey: rawKey } = await params;
  const cycleKey = decodeURIComponent(rawKey);
  const fund = getDefaultFund();
  if (!fund) return <FundEmpty />;

  const cycle = getCycle(fund.fund_id, cycleKey);
  if (!cycle) notFound();

  const all = listCycles(fund.fund_id);
  const index = all.findIndex((c) => c.cycle_key === cycle.cycle_key);
  const prev = index > 0 ? all[index - 1] : null;
  const next = index >= 0 && index < all.length - 1 ? all[index + 1] : null;
  const fills = [...cycle.fills, ...cycle.settlements];
  const risk = cycle.audit?.risk ?? null;
  const runtime = cycle.audit?.runtime ?? null;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href="/cycles"
            className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase hover:text-foreground"
          >
            ← Cycles
          </Link>
        </div>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate font-mono text-base font-medium tracking-tight">
                {cycle.cycle_key}
              </h2>
              <Badge
                variant="outline"
                className={cn(
                  "font-mono text-[10px] capitalize",
                  actionBadgeClass(cycle.action),
                )}
              >
                {cycle.action}
              </Badge>
              {risk ? (
                <Badge
                  variant="outline"
                  className={cn(
                    "font-mono text-[10px]",
                    risk.approved
                      ? "border-success/30 bg-success/15 text-success"
                      : "border-danger/30 bg-danger/15 text-danger",
                  )}
                >
                  {risk.approved ? "risk approved" : "risk rejected"}
                </Badge>
              ) : null}
            </div>
            <p className="mt-0.5 font-mono text-xs text-muted-foreground tabular-nums">
              {formatTs(cycle.as_of)} · digest {truncateId(cycle.request_digest, 12)}
            </p>
          </div>
          <div className="flex gap-3 font-mono text-xs tabular-nums">
            {prev ? (
              <Link
                href={cycleHref(prev.cycle_key)}
                className="text-muted-foreground hover:text-foreground hover:underline"
              >
                ← {prev.cycle_key}
              </Link>
            ) : null}
            {next ? (
              <Link
                href={cycleHref(next.cycle_key)}
                className="text-muted-foreground hover:text-foreground hover:underline"
              >
                {next.cycle_key} →
              </Link>
            ) : null}
          </div>
        </div>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg border border-border bg-card px-3.5 py-3">
          <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            NAV after
          </p>
          <p className="mt-1 font-mono text-lg tabular-nums">
            {formatUsd(cycle.state.nav)}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card px-3.5 py-3">
          <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Cash
          </p>
          <p className="mt-1 font-mono text-lg tabular-nums">
            {formatUsd(cycle.state.cash)}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card px-3.5 py-3">
          <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Fills
          </p>
          <p className="mt-1 font-mono text-lg tabular-nums">{fills.length}</p>
        </div>
        <div className="rounded-lg border border-border bg-card px-3.5 py-3">
          <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Fees
          </p>
          <p className="mt-1 font-mono text-lg tabular-nums">
            {formatUsd(cycle.audit?.fee_total ?? "0")}
          </p>
        </div>
      </section>

      <Panel micro="Decision" title="Thesis" bodyClassName="flex flex-col gap-4 px-3.5 py-3">
        <p className="text-sm leading-relaxed">{cycle.thesis || "No thesis."}</p>
        {cycle.alternatives ? (
          <JournalBlock label="Alternatives">{cycle.alternatives}</JournalBlock>
        ) : null}
        {cycle.risks ? (
          <JournalBlock label="Risks">{cycle.risks}</JournalBlock>
        ) : null}
      </Panel>

      <Panel
        micro="Journal"
        title="Auditable reasoning"
        trailing={cycle.journal ? "v1" : "absent"}
        bodyClassName="flex flex-col gap-4 px-3.5 py-3"
      >
        {cycle.journal ? (
          <>
            <JournalBlock label="Market regime">
              {cycle.journal.market_regime}
            </JournalBlock>
            <JournalBlock label="Opportunity set">
              {cycle.journal.opportunity_set}
            </JournalBlock>
            <JournalBlock label="Portfolio intent">
              {cycle.journal.portfolio_intent}
            </JournalBlock>
            <JournalBlock label="What changed">
              {cycle.journal.what_changed}
            </JournalBlock>
            {cycle.journal.lessons_applied.length > 0 ? (
              <div>
                <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Lessons applied
                </p>
                <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-foreground">
                  {cycle.journal.lessons_applied.map((lesson) => (
                    <li key={lesson}>{lesson}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            This historical cycle has no journal sidecar. Accounting replay still
            holds.
          </p>
        )}
      </Panel>

      <Panel
        micro="Hypotheses"
        title="Instrument theses"
        trailing={`${cycle.journal?.hypotheses.length ?? 0}`}
      >
        <HypothesisTable
          hypotheses={cycle.journal?.hypotheses ?? []}
          empty="No instrument hypotheses on this cycle."
        />
      </Panel>

      {cycle.journal?.hypotheses.map((h) => (
        <Panel
          key={h.instrument_id}
          micro="Hypothesis"
          title={h.instrument_id}
          trailing={h.stance}
          bodyClassName="grid gap-3 px-3.5 py-3 sm:grid-cols-2"
        >
          <JournalBlock label="Mechanism">{h.mechanism}</JournalBlock>
          <div>
            <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
              Catalysts
            </p>
            <ul className="mt-1 list-disc space-y-1 pl-4 text-sm">
              {h.catalysts.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div>
            <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
              Falsifiers
            </p>
            <ul className="mt-1 list-disc space-y-1 pl-4 text-sm">
              {h.falsifiers.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <p className="font-mono text-xs text-muted-foreground tabular-nums sm:col-span-2">
            horizon {h.expected_horizon_hours}h · evidence{" "}
            {h.evidence_ids.join(", ") || "—"}
          </p>
        </Panel>
      ))}

      <Panel micro="Orders" title="Explicit sides" trailing={`${cycle.orders.length}`}>
        {cycle.orders.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-muted-foreground">
            Hold — no orders.
          </p>
        ) : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-3.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Instrument
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Side
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Qty
                </TableHead>
                <TableHead className="pr-3.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Rationale
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {cycle.orders.map((order, i) => (
                <TableRow key={`${order.instrument_id}:${order.side}:${i}`}>
                  <TableCell className="pl-3.5 font-mono font-medium">
                    {order.instrument_id}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className={cn(
                        "font-mono text-[10px] capitalize",
                        sideBadgeClass(order.side),
                      )}
                    >
                      {order.side}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatQty(order.quantity)}
                  </TableCell>
                  <TableCell className="max-w-[32rem] truncate pr-3.5 text-muted-foreground whitespace-normal">
                    {order.rationale}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Panel>

      <Panel micro="Evidence" title="Cited sources" trailing={`${cycle.evidence.length}`}>
        {cycle.evidence.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-muted-foreground">
            No embedded evidence on this cycle.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {cycle.evidence.map((item) => (
              <li key={item.evidence_id} className="px-3.5 py-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="font-mono text-xs text-foreground">
                    {item.evidence_id}
                  </p>
                  <p className="font-mono text-[10px] text-muted-foreground tabular-nums">
                    {formatTs(item.observed_at)} · {item.source_name}
                  </p>
                </div>
                <p className="mt-1 text-sm">{item.claim}</p>
                {item.source_url ? (
                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-block max-w-full truncate font-mono text-[11px] text-indigo-300 hover:underline"
                  >
                    {item.source_url}
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel micro="Execution" title="Simulated fills" trailing={`${fills.length}`}>
        {fills.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-muted-foreground">
            No simulated fills this cycle.
          </p>
        ) : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-3.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Instrument
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Side
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Qty
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Exec
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Gross
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Fee
                </TableHead>
                <TableHead className="pr-3.5 text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Realized
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {fills.map((fill) => (
                <TableRow key={fill.fill_id}>
                  <TableCell className="pl-3.5 font-mono font-medium">
                    {fill.instrument_id}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className={cn(
                        "font-mono text-[10px] capitalize",
                        sideBadgeClass(fill.side),
                      )}
                    >
                      {fill.side}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatQty(fill.quantity)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatUsd(fill.execution_price)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatUsd(fill.gross_notional)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums text-muted-foreground">
                    {formatUsd(fill.fee)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "pr-3.5 text-right font-mono tabular-nums",
                      pnlClass(num(fill.realized_pnl)),
                    )}
                  >
                    {formatUsd(fill.realized_pnl, { signed: true })}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Panel>

      <Panel
        micro="Audit"
        title="Risk + provenance"
        trailing={runtime?.model ?? runtime?.edgecraft_version ?? "—"}
        bodyClassName="flex flex-col gap-4 px-3.5 py-3"
      >
        {runtime ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 font-mono text-xs sm:grid-cols-3">
            <dt className="text-muted-foreground">version</dt>
            <dd className="col-span-1 sm:col-span-2 tabular-nums">
              {runtime.edgecraft_version}
            </dd>
            <dt className="text-muted-foreground">model</dt>
            <dd className="col-span-1 sm:col-span-2">{runtime.model ?? "—"}</dd>
            <dt className="text-muted-foreground">prompt</dt>
            <dd className="col-span-1 truncate sm:col-span-2">
              {runtime.prompt_version ?? "—"}
            </dd>
            <dt className="text-muted-foreground">input sha</dt>
            <dd className="col-span-1 truncate sm:col-span-2 tabular-nums">
              {runtime.input_sha256 ?? "—"}
            </dd>
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">
            No runtime provenance sidecar.
          </p>
        )}

        {risk && risk.checks.length > 0 ? (
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-0 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Check
                </TableHead>
                <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Result
                </TableHead>
                <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Observed
                </TableHead>
                <TableHead className="pr-0 text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
                  Limit
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {risk.checks.map((check) => (
                <TableRow key={check.name}>
                  <TableCell className="pl-0 font-mono">{check.name}</TableCell>
                  <TableCell>
                    <span
                      className={
                        check.passed ? "text-success" : "text-danger"
                      }
                    >
                      {check.passed ? "pass" : "fail"}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {check.observed}
                  </TableCell>
                  <TableCell className="pr-0 text-right font-mono tabular-nums text-muted-foreground">
                    {check.limit ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </Panel>
    </div>
  );
}
