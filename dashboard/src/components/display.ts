import { formatPrice, formatQty } from "@/components/format";
import { asNumber } from "@/lib/numbers";
import type { Cycle, FundHypothesis, Position } from "@/lib/types";

export { asNumber as num } from "@/lib/numbers";

export function pnlClass(value: number): string {
  if (value > 0) return "text-gain";
  if (value < 0) return "text-loss";
  return "text-graphite";
}

export function capitalize(value: string): string {
  return value ? value[0].toUpperCase() + value.slice(1) : value;
}

const ACTIONS: Record<string, string> = { trade: "Traded", hold: "Held", rejected: "Rejected" };

export function actionLabel(action: string): string {
  return ACTIONS[action] ?? capitalize(action);
}

export function cycleHref(cycleKey: string, fundId?: string): string {
  return `/cycles/${encodeURIComponent(cycleKey)}${fundId ? `?fund=${encodeURIComponent(fundId)}` : ""}`;
}

export function positionHref(instrumentId: string, fundId?: string): string {
  return `/positions/${encodeURIComponent(instrumentId)}${fundId ? `?fund=${encodeURIComponent(fundId)}` : ""}`;
}

export function openPositions<T extends { quantity: string | number | null }>(
  positions: T[],
): T[] {
  return positions.filter((p) => asNumber(p.quantity) !== 0);
}

/** "polymarket:5795746:NO" holds the No side; stock tickers have no outcome. */
export function contractOutcome(instrumentId: string): "Yes" | "No" | null {
  if (instrumentId.endsWith(":YES")) return "Yes";
  if (instrumentId.endsWith(":NO")) return "No";
  return null;
}

/** "500 Yes at 32¢, now 52¢" or "Short 2 shares at $180.00, now $176.10". */
export function holdingDetail(p: Position): string {
  const outcome = contractOutcome(p.instrument_id);
  const qty = asNumber(p.quantity);
  const entry = formatPrice(p.average_entry, p.asset_class);
  const mark = formatPrice(p.mark_price, p.asset_class);
  if (outcome) return `${formatQty(qty)} ${outcome} at ${entry}, now ${mark}`;
  const shares = `${formatQty(Math.abs(qty))} ${Math.abs(qty) === 1 ? "share" : "shares"}`;
  return `${qty < 0 ? "Short" : "Long"} ${shares} at ${entry}, now ${mark}`;
}

/** "Target 60¢, exit at 20¢, within 48h". */
export function beliefLine(h: FundHypothesis): string {
  const asset = contractOutcome(h.instrument_id) ? "prediction" : undefined;
  const parts = asset ? [] : [capitalize(h.stance)];
  if (h.target_price != null) parts.push(`target ${formatPrice(h.target_price, asset)}`);
  if (h.invalidation_price != null) parts.push(`exit at ${formatPrice(h.invalidation_price, asset)}`);
  parts.push(`within ${h.expected_horizon_hours}h`);
  return capitalize(parts.join(", "));
}

/** The claim before the colon, e.g. "Milan Malpensa (LIMC) high is not 21C". */
function headline(text: string | null | undefined): string | null {
  const head = (text ?? "").split(": ")[0].trim().replace(/\.$/, "");
  return head && head.length <= 96 ? head : null;
}

/**
 * Human names for contracts, taken from what the researcher wrote about them.
 * Order rationales describe the side actually bought, so they win.
 */
export function contractTitles(cycles: Cycle[]): Map<string, string> {
  const titles = new Map<string, string>();
  for (const cycle of cycles) {
    for (const h of cycle.journal?.hypotheses ?? []) {
      const title = headline(h.statement);
      if (title) titles.set(h.instrument_id, title);
    }
    for (const order of cycle.orders) {
      const title = headline(order.rationale);
      if (title) titles.set(order.instrument_id, title);
    }
  }
  return titles;
}

export function contractName(
  titles: Map<string, string>,
  instrumentId: string,
  assetClass?: string,
): string {
  if (assetClass && assetClass !== "prediction") return instrumentId;
  return titles.get(instrumentId) ?? instrumentId;
}
