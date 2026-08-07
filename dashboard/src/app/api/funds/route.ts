import { NextResponse } from "next/server";
import { listFunds } from "@/lib/fund";

export const runtime = "nodejs";

export async function GET() {
  try {
    const funds = listFunds();
    return NextResponse.json({ funds });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to list funds";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
