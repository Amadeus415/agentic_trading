/** Shared numeric coercion for ledger decimals stored as strings. */

export function asNumber(
  value: string | number | null | undefined,
  fallback = 0,
): number {
  if (value === null || value === undefined || value === "") return fallback;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
}
