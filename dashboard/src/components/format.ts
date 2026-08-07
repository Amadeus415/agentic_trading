/**
 * Display formatters for fund metrics.
 * Money and quantities never render raw float noise — decimals are capped.
 */

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const USD_COMPACT = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 2,
});

const PCT = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});

const QTY = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 6,
});

const TS = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZone: "UTC",
  timeZoneName: "short",
});

const TS_DATE = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "2-digit",
  timeZone: "UTC",
});

function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Format USD with 2 decimal places. Compact for |value| ≥ 1e6 when compact=true. */
export function formatUsd(
  value: number | string | null | undefined,
  options?: { compact?: boolean; signed?: boolean }
): string {
  const n = toNumber(value);
  if (n === null) return "—";
  const abs = Math.abs(n);
  const formatted =
    options?.compact && abs >= 1_000_000 ? USD_COMPACT.format(n) : USD.format(n);
  if (options?.signed && n > 0) return `+${formatted}`;
  return formatted;
}

/**
 * Format a ratio or percent.
 * Pass ratios (0.05 → +5.00%) by default; set alreadyPercent for 5 → +5.00%.
 */
export function formatPct(
  value: number | string | null | undefined,
  options?: { alreadyPercent?: boolean }
): string {
  const n = toNumber(value);
  if (n === null) return "—";
  const ratio = options?.alreadyPercent ? n / 100 : n;
  return PCT.format(ratio);
}

/** Format quantity with up to 6 fraction digits (no trailing noise beyond that). */
export function formatQty(value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return "—";
  // Cap float noise: round to 6 dp before format
  const rounded = Math.round(n * 1e6) / 1e6;
  return QTY.format(rounded);
}

/** Format ISO/UTC timestamps for tables and audit UI. dateOnly skips time. */
export function formatTs(
  value: string | number | Date | null | undefined,
  options?: { dateOnly?: boolean }
): string {
  if (value === null || value === undefined || value === "") return "—";
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return options?.dateOnly ? TS_DATE.format(d) : TS.format(d);
}
