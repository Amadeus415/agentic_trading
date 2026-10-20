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

const PCT = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

const QTY = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 4,
});

const CENTS = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 1,
});

const TS = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

const DAY = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

const DAY_YEAR = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Format USD with 2 decimal places; signed adds "+" and a true minus sign. */
export function formatUsd(
  value: number | string | null | undefined,
  options?: { signed?: boolean },
): string {
  const n = toNumber(value);
  if (n === null) return "—";
  const formatted = USD.format(Math.abs(n));
  if (n < 0 && formatted !== "$0.00") return `−${formatted}`;
  if (options?.signed && n > 0 && formatted !== "$0.00") return `+${formatted}`;
  return formatted;
}

/**
 * Format a ratio or percent. Pass ratios (0.05 → 5%) by default;
 * set alreadyPercent for 5 → 5%. Signed adds "+" to gains.
 */
export function formatPct(
  value: number | string | null | undefined,
  options?: { alreadyPercent?: boolean; signed?: boolean },
): string {
  const n = toNumber(value);
  if (n === null) return "—";
  const ratio = options?.alreadyPercent ? n / 100 : n;
  const formatted = PCT.format(Math.abs(ratio));
  if (ratio < 0 && formatted !== "0%") return `−${formatted}`;
  if (options?.signed && ratio > 0 && formatted !== "0%") return `+${formatted}`;
  return formatted;
}

/** Format quantity with up to 4 fraction digits. */
export function formatQty(value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return "—";
  return QTY.format(Math.round(n * 1e4) / 1e4);
}

/** Event contracts trade between $0 and $1, so they read best in cents. */
export function formatPrice(
  value: number | string | null | undefined,
  assetClass?: string,
): string {
  const n = toNumber(value);
  if (n === null) return "—";
  if (assetClass === "prediction") return `${CENTS.format(n * 100)}¢`;
  return formatUsd(n);
}

/** "Oct 19, 03:28 UTC" — every timestamp in the ledger is UTC. */
export function formatTs(value: string | number | Date | null | undefined): string {
  const d = toDate(value);
  return d ? `${TS.format(d)} UTC` : "—";
}

/** "Oct 19", or "Oct 19, 2025" outside the current year. */
export function formatDay(value: string | number | Date | null | undefined): string {
  const d = toDate(value);
  if (!d) return "—";
  return d.getUTCFullYear() === new Date().getUTCFullYear() ? DAY.format(d) : DAY_YEAR.format(d);
}
