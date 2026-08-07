import { NextResponse } from "next/server";
import { getFund, getLatestState, listCycles } from "@/lib/fund";

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
    const state = getLatestState(fundId);
    const cycles = listCycles(fundId);
    return NextResponse.json({
      fund,
      state,
      cycle_count: cycles.length,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to load fund";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
