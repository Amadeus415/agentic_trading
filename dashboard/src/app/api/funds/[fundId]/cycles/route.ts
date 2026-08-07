import { NextResponse } from "next/server";
import { getFund, listCycles, toCycleListItems } from "@/lib/fund";

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
    // Newest first for the activity feed.
    const items = toCycleListItems(cycles).reverse();

    return NextResponse.json({
      fund_id: fund.fund_id,
      cycles: items,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to load cycles";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
