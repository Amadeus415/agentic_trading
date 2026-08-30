import { formatPct, formatUsd } from "@/components/format";
import { stanceBadgeClass } from "@/components/display";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { FundHypothesis } from "@/lib/types";
import { cn } from "@/lib/utils";

export function HypothesisTable({
  hypotheses,
  empty = "No hypotheses recorded for this cycle.",
}: {
  hypotheses: FundHypothesis[];
  empty?: string;
}) {
  if (hypotheses.length === 0) {
    return (
      <p className="px-3.5 py-8 text-center text-sm text-muted-foreground">
        {empty}
      </p>
    );
  }

  return (
    <Table className="text-xs">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="pl-3.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Instrument
          </TableHead>
          <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Stance
          </TableHead>
          <TableHead className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Statement
          </TableHead>
          <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Horizon
          </TableHead>
          <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Conf
          </TableHead>
          <TableHead className="text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Target
          </TableHead>
          <TableHead className="pr-3.5 text-right font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
            Invalidation
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {hypotheses.map((h) => (
          <TableRow key={h.instrument_id}>
            <TableCell className="pl-3.5 font-mono text-sm font-medium tabular-nums">
              {h.instrument_id}
            </TableCell>
            <TableCell>
              <Badge
                variant="outline"
                className={cn(
                  "font-mono text-[10px] capitalize",
                  stanceBadgeClass(h.stance),
                )}
              >
                {h.stance}
              </Badge>
            </TableCell>
            <TableCell className="max-w-[28rem] truncate text-sm text-muted-foreground whitespace-normal">
              {h.statement}
            </TableCell>
            <TableCell className="text-right font-mono tabular-nums">
              {h.expected_horizon_hours}h
            </TableCell>
            <TableCell className="text-right font-mono tabular-nums">
              {formatPct(h.confidence)}
            </TableCell>
            <TableCell className="text-right font-mono tabular-nums">
              {h.target_price != null ? formatUsd(h.target_price) : "—"}
            </TableCell>
            <TableCell className="pr-3.5 text-right font-mono tabular-nums">
              {h.invalidation_price != null
                ? formatUsd(h.invalidation_price)
                : "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
