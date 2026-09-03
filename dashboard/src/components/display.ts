import type { StatDeltaTone } from "@/components/stat-card";
import { asNumber } from "@/lib/numbers";

export { asNumber as num } from "@/lib/numbers";

export function pnlClass(value: number): string {
  if (value > 0) return "text-success";
  if (value < 0) return "text-danger";
  return "text-muted-foreground";
}

export function toneForSigned(value: number): StatDeltaTone {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "neutral";
}

export function sideBadgeClass(side: string): string {
  switch (side) {
    case "buy":
      return "border-success/30 bg-success/15 text-success";
    case "sell":
      return "border-danger/30 bg-danger/15 text-danger";
    case "short":
      return "border-amber-500/30 bg-amber-500/15 text-amber-300";
    case "cover":
      return "border-indigo-400/30 bg-indigo-400/15 text-indigo-300";
    case "settle":
      return "border-border bg-muted text-muted-foreground";
    default:
      return "border-border bg-secondary text-secondary-foreground";
  }
}

export function actionBadgeClass(action: string): string {
  if (action === "trade")
    return "border-indigo-400/30 bg-indigo-400/10 text-indigo-300";
  if (action === "hold") return "border-border bg-muted text-muted-foreground";
  if (action === "rejected")
    return "border-danger/30 bg-danger/15 text-danger";
  return "border-border bg-secondary text-secondary-foreground";
}

export function stanceBadgeClass(stance: string): string {
  switch (stance) {
    case "long":
      return "border-success/30 bg-success/15 text-success";
    case "short":
      return "border-amber-500/30 bg-amber-500/15 text-amber-300";
    case "exit":
      return "border-danger/30 bg-danger/15 text-danger";
    default:
      return "border-border bg-secondary text-secondary-foreground";
  }
}

export function outcomeBadgeClass(outcome: string): string {
  if (outcome === "positive")
    return "border-success/30 bg-success/15 text-success";
  if (outcome === "negative")
    return "border-danger/30 bg-danger/15 text-danger";
  return "border-border bg-muted text-muted-foreground";
}

export function truncateId(id: string, head = 8): string {
  if (!id) return "—";
  if (id.length <= head + 4) return id;
  return `${id.slice(0, head)}…`;
}

export function cycleHref(cycleKey: string): string {
  return `/cycles/${encodeURIComponent(cycleKey)}`;
}

export function openPositions<T extends { quantity: string | number | null }>(
  positions: T[],
): T[] {
  return positions.filter((p) => asNumber(p.quantity) !== 0);
}
