import { NextResponse } from "next/server";
import {
  extractFillsFromCycles,
  getFund,
  listCycles,
} from "@/lib/fund";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ fundId: string }>;
};

export async function GET(_request: Request, context: RouteContext) {
  try {
    const { fundId } = await context.params;
    const fund = getFund(fundId);
    if (!fund) {
      return NextResponse.json({ error: "Fund not found" }, { status: 404 });
    }

    const cycles = listCycles(fundId);
    const trades = extractFillsFromCycles(cycles);
    const cycle_metadata = cycles.map((c) => ({
      cycle_key: c.cycle_key,
      decision_id: c.decision_id,
      as_of: c.as_of,
      action: c.action,
      created_at: c.created_at,
      fill_count: c.fills.length,
      nav: c.state?.nav ?? null,
    }));

    return NextResponse.json({
      trades,
      cycle_metadata,
      fund_id: fund.fund_id,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to load trades";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
