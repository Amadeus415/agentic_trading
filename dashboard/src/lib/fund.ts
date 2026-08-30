/**
 * Fund query helpers and pure series/metrics builders for the dashboard.
 * All DB access is read-only via src/lib/db.ts.
 */
import { getDb } from "./db";
import { buildFundBrain } from "./brain";
import { buildGrowthSnapshot, growthObjectiveFromMandate } from "./growth";
import { asNumber } from "./numbers";
import type {
  AuditEvent,
  Cycle,
  CycleListItem,
  Fill,
  Fund,
  FundBrainSnapshot,
  FundHypothesis,
  FundQuote,
  PerformanceHistory,
  FundState,
  PerformancePoint,
  Position,
  SummaryMetrics,
  TradeRow,
} from "./types";

function parseJson<T>(raw: string, fallback: T): T {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function mapFill(raw: Record<string, unknown>): Fill {
  return {
    fill_id: String(raw.fill_id ?? ""),
    instrument_id: String(raw.instrument_id ?? ""),
    asset_class: String(raw.asset_class ?? ""),
    side: String(raw.side ?? "buy") as Fill["side"],
    quantity: String(raw.quantity ?? "0"),
    quote_price: String(raw.quote_price ?? "0"),
    execution_price: String(raw.execution_price ?? "0"),
    gross_notional: String(raw.gross_notional ?? "0"),
    fee: String(raw.fee ?? "0"),
    cash_delta: String(raw.cash_delta ?? "0"),
    realized_pnl: String(raw.realized_pnl ?? "0"),
    quote_id: String(raw.quote_id ?? ""),
    is_settlement: Boolean(raw.is_settlement),
  };
}

function mapPosition(raw: Record<string, unknown>): Position {
  return {
    instrument_id: String(raw.instrument_id ?? ""),
    asset_class: String(raw.asset_class ?? ""),
    quantity: String(raw.quantity ?? "0"),
    average_entry: String(raw.average_entry ?? "0"),
    mark_price: raw.mark_price == null ? null : String(raw.mark_price),
    market_value: raw.market_value == null ? null : String(raw.market_value),
    unrealized_pnl: raw.unrealized_pnl == null ? null : String(raw.unrealized_pnl),
  };
}

function mapState(raw: Record<string, unknown>): FundState {
  const positionsRaw = Array.isArray(raw.positions) ? raw.positions : [];
  return {
    fund_id: String(raw.fund_id ?? ""),
    as_of: String(raw.as_of ?? ""),
    cash: String(raw.cash ?? "0"),
    positions: positionsRaw.map((p) => mapPosition(p as Record<string, unknown>)),
    nav: String(raw.nav ?? "0"),
    peak_nav: String(raw.peak_nav ?? "0"),
    drawdown: String(raw.drawdown ?? "0"),
    gross_exposure: String(raw.gross_exposure ?? "0"),
    net_exposure: String(raw.net_exposure ?? "0"),
    short_exposure: String(raw.short_exposure ?? "0"),
    realized_pnl_cumulative: String(raw.realized_pnl_cumulative ?? "0"),
    cycle_count: Number(raw.cycle_count ?? 0) || 0,
    last_cycle_key:
      raw.last_cycle_key === null || raw.last_cycle_key === undefined
        ? null
        : String(raw.last_cycle_key),
  };
}

type CycleRow = {
  fund_id: string;
  cycle_key: string;
  decision_id: string;
  as_of: string;
  action: string;
  request_digest: string;
  decision_json: string;
  quotes_json: string;
  fills_json: string;
  settlements_json: string;
  state_json: string;
  result_json: string;
  created_at: string;
};

function rowToCycle(row: CycleRow): Cycle {
  const decision = parseJson<Record<string, unknown>>(row.decision_json, {});
  const quotes = parseJson<FundQuote[]>(row.quotes_json, []);
  const fillsRaw = parseJson<Record<string, unknown>[]>(row.fills_json, []);
  const settlementsRaw = parseJson<Record<string, unknown>[]>(row.settlements_json, []);
  const stateRaw = parseJson<Record<string, unknown>>(row.state_json, {});
  const result = parseJson<Record<string, unknown>>(row.result_json, {});

  return {
    fund_id: row.fund_id,
    cycle_key: row.cycle_key,
    decision_id: row.decision_id,
    as_of: row.as_of,
    action: row.action,
    request_digest: row.request_digest,
    created_at: row.created_at,
    decision,
    quotes: (Array.isArray(quotes) ? quotes : []) as Cycle["quotes"],
    fills: fillsRaw.map(mapFill),
    settlements: settlementsRaw.map(mapFill),
    state: mapState(stateRaw),
    result,
    thesis: String(decision.thesis ?? ""),
    alternatives: String(decision.alternatives ?? ""),
    risks: String(decision.risks ?? ""),
    journal: (decision.journal ?? null) as Cycle["journal"],
    orders: (Array.isArray(decision.orders) ? decision.orders : []) as Cycle["orders"],
    evidence: (Array.isArray(decision.evidence) ? decision.evidence : []) as Cycle["evidence"],
    audit: (result.audit ?? null) as Cycle["audit"],
    decision_json: row.decision_json,
    quotes_json: row.quotes_json,
    fills_json: row.fills_json,
    settlements_json: row.settlements_json,
    state_json: row.state_json,
    result_json: row.result_json,
  };
}

export function listFunds(): Fund[] {
  const db = getDb();
  const rows = db
    .prepare(
      `SELECT fund_id, created_at, mandate_json, initial_cash
       FROM funds
       ORDER BY created_at ASC`,
    )
    .all() as Array<{
    fund_id: string;
    created_at: string;
    mandate_json: string;
    initial_cash: string;
  }>;

  return rows.map((row) => ({
    fund_id: row.fund_id,
    created_at: row.created_at,
    initial_cash: row.initial_cash,
    mandate_json: row.mandate_json,
    mandate: parseJson<Record<string, unknown>>(row.mandate_json, {}),
  }));
}

export function getFund(fundId: string): Fund | null {
  const db = getDb();
  const row = db
    .prepare(
      `SELECT fund_id, created_at, mandate_json, initial_cash
       FROM funds
       WHERE fund_id = ?`,
    )
    .get(fundId) as
    | {
        fund_id: string;
        created_at: string;
        mandate_json: string;
        initial_cash: string;
      }
    | undefined;

  if (!row) return null;
  return {
    fund_id: row.fund_id,
    created_at: row.created_at,
    initial_cash: row.initial_cash,
    mandate_json: row.mandate_json,
    mandate: parseJson<Record<string, unknown>>(row.mandate_json, {}),
  };
}

export function getDefaultFund(): Fund | null {
  return listFunds()[0] ?? null;
}

export function listCycles(fundId: string): Cycle[] {
  const db = getDb();
  const rows = db
    .prepare(
      `SELECT fund_id, cycle_key, decision_id, as_of, action, request_digest,
              decision_json, quotes_json, fills_json, settlements_json,
              state_json, result_json, created_at
       FROM cycles
       WHERE fund_id = ?
       ORDER BY as_of ASC, created_at ASC`,
    )
    .all(fundId) as CycleRow[];

  return rows.map(rowToCycle);
}

export function getCycle(fundId: string, cycleKey: string): Cycle | null {
  return listCycles(fundId).find((cycle) => cycle.cycle_key === cycleKey) ?? null;
}

export function listEvents(fundId: string): AuditEvent[] {
  const rows = getDb().prepare(
    `SELECT sequence, event_type, occurred_at, payload_json, prev_hash, event_hash
     FROM events WHERE fund_id = ? ORDER BY sequence ASC`,
  ).all(fundId) as Array<{
    sequence: number; event_type: string; occurred_at: string; payload_json: string;
    prev_hash: string; event_hash: string;
  }>;
  return rows.map((row) => ({
    sequence: row.sequence,
    event_type: row.event_type,
    occurred_at: row.occurred_at,
    payload: parseJson<Record<string, unknown>>(row.payload_json, {}),
    prev_hash: row.prev_hash,
    event_hash: row.event_hash,
  }));
}

/** Latest FundState for a fund, or a synthetic initial state when no cycles exist. */
export function getLatestState(fundId: string): FundState | null {
  const fund = getFund(fundId);
  if (!fund) return null;

  const db = getDb();
  const row = db
    .prepare(
      `SELECT state_json
       FROM cycles
       WHERE fund_id = ?
       ORDER BY as_of DESC, created_at DESC
       LIMIT 1`,
    )
    .get(fundId) as { state_json: string } | undefined;

  if (row) {
    return mapState(parseJson<Record<string, unknown>>(row.state_json, {}));
  }

  return {
    fund_id: fund.fund_id,
    as_of: fund.created_at,
    cash: fund.initial_cash,
    positions: [],
    nav: fund.initial_cash,
    peak_nav: fund.initial_cash,
    drawdown: "0",
    gross_exposure: "0",
    net_exposure: "0",
    short_exposure: "0",
    realized_pnl_cumulative: "0",
    cycle_count: 0,
    last_cycle_key: null,
  };
}

/** Flatten all fills across cycles into TradeRow[] ordered by as_of. */
export function extractFillsFromCycles(cycles: Cycle[]): TradeRow[] {
  const rows: TradeRow[] = [];
  for (const cycle of cycles) {
    for (const fill of [...cycle.fills, ...cycle.settlements]) {
      rows.push({
        ...fill,
        fund_id: cycle.fund_id,
        cycle_key: cycle.cycle_key,
        as_of: cycle.as_of,
      });
    }
  }
  rows.sort((a, b) => {
    const t = a.as_of.localeCompare(b.as_of);
    if (t !== 0) return t;
    return a.fill_id.localeCompare(b.fill_id);
  });
  return rows;
}

/**
 * NAV series starting at initial_cash @ fund.created_at, then each cycle's
 * state.nav at cycle.as_of.
 */
export function buildNavSeries(fund: Fund, cycles: Cycle[]): PerformancePoint[] {
  const initial = asNumber(fund.initial_cash);
  const points: PerformancePoint[] = [
    {
      as_of: fund.created_at,
      value: initial,
      nav: initial,
    },
  ];

  const ordered = [...cycles].sort((a, b) => {
    const t = a.as_of.localeCompare(b.as_of);
    if (t !== 0) return t;
    return a.created_at.localeCompare(b.created_at);
  });

  for (const cycle of ordered) {
    const nav = asNumber(cycle.state?.nav, initial);
    points.push({
      as_of: cycle.as_of,
      value: nav,
      nav,
    });
  }

  return points;
}

export function summaryMetrics(
  navSeries: PerformancePoint[],
  positions: Position[],
  options?: {
    cash?: number | string; peakNav?: number | string; drawdown?: number | string;
    grossExposure?: number | string; netExposure?: number | string; shortExposure?: number | string;
    realizedPnl?: number | string; fillCount?: number; tradeCycleCount?: number;
    holdCycleCount?: number; cycleCount?: number;
  },
): SummaryMetrics {
  const first = navSeries[0];
  const last = navSeries[navSeries.length - 1];
  const initialCash = first?.nav ?? first?.value ?? 0;
  const currentNav = last?.nav ?? last?.value ?? initialCash;

  let peakNav = asNumber(options?.peakNav, initialCash);
  if (options?.peakNav === undefined) {
    peakNav = navSeries.reduce((peak, p) => Math.max(peak, p.nav ?? p.value), initialCash);
  }

  let drawdown = asNumber(options?.drawdown, 0);
  if (options?.drawdown === undefined) {
    drawdown = peakNav > 0 ? Math.max(0, (peakNav - currentNav) / peakNav) : 0;
  }

  if (options?.cash === undefined) {
    throw new Error("summaryMetrics requires cash from the stored fund state");
  }
  const cash = asNumber(options.cash);

  const totalReturnPct =
    initialCash > 0 ? ((currentNav - initialCash) / initialCash) * 100 : 0;

  return {
    currentNav,
    cash,
    drawdown,
    peakNav,
    totalReturnPct,
    positionCount: positions.filter((p) => asNumber(p.quantity) !== 0).length,
    profitAndLoss: currentNav - initialCash,
    grossExposure: asNumber(options?.grossExposure),
    netExposure: asNumber(options?.netExposure),
    shortExposure: asNumber(options?.shortExposure),
    realizedPnl: asNumber(options?.realizedPnl),
    fillCount: options?.fillCount ?? 0,
    tradeCount: options?.fillCount ?? 0,
    tradeCycleCount: options?.tradeCycleCount ?? 0,
    holdCycleCount: options?.holdCycleCount ?? 0,
    cycleCount: options?.cycleCount ?? 0,
    initialCash,
  };
}

/** Build cycle list items with action + thesis snippet for the cycles API. */
export function toCycleListItems(cycles: Cycle[]): CycleListItem[] {
  return cycles.map((cycle) => {
    const thesis = String(cycle.decision?.thesis ?? "");
    const snippet =
      thesis.length > 180 ? `${thesis.slice(0, 177).trimEnd()}...` : thesis;
    return {
      fund_id: cycle.fund_id,
      cycle_key: cycle.cycle_key,
      decision_id: cycle.decision_id,
      as_of: cycle.as_of,
      action: cycle.action,
      created_at: cycle.created_at,
      nav: cycle.state?.nav ?? null,
      fill_count: (cycle.fills?.length ?? 0) + (cycle.settlements?.length ?? 0),
      order_count: cycle.orders.length,
      thesis,
      what_changed: cycle.journal?.what_changed ?? null,
      risk_approved: cycle.audit?.risk?.approved ?? null,
      fee_total: cycle.audit?.fee_total ?? null,
      decision_summary: {
        action: String(cycle.decision?.action ?? cycle.action),
        thesis_snippet: snippet,
      },
    };
  });
}

export function latestHypothesesByInstrument(cycles: Cycle[]): Map<string, FundHypothesis> {
  const hypotheses = new Map<string, FundHypothesis>();
  for (const cycle of cycles) {
    for (const hypothesis of cycle.journal?.hypotheses ?? []) {
      hypotheses.set(hypothesis.instrument_id, hypothesis);
    }
  }
  return hypotheses;
}

export function buildPerformanceHistory(
  fund: Fund,
  cycles: Cycle[],
  state: FundState,
): PerformanceHistory {
  const navs = [asNumber(fund.initial_cash), ...cycles.map((cycle) => asNumber(cycle.state.nav))];
  const changes = navs.slice(1).map((nav, index) => nav - navs[index]);
  const initialCash = asNumber(fund.initial_cash);
  const currentNav = asNumber(state.nav);
  return {
    status: cycles.length < 20 ? "measuring" : "active",
    initialCash,
    currentNav,
    profitAndLoss: currentNav - initialCash,
    totalReturn: initialCash > 0 ? currentNav / initialCash - 1 : 0,
    maxDrawdown: Math.max(0, ...cycles.map((cycle) => asNumber(cycle.state.drawdown))),
    positiveCycleCount: changes.filter((change) => change > 0).length,
    negativeCycleCount: changes.filter((change) => change < 0).length,
    holdCount: cycles.filter((cycle) => cycle.action === "hold").length,
    tradeCount: cycles.filter((cycle) => cycle.action === "trade").length,
    simulatedFillCount: cycles.reduce((count, cycle) => count + cycle.fills.length + cycle.settlements.length, 0),
    interpretation: `Raw bankroll performance through ${state.cycle_count} cycles; a longer frozen history and market benchmark are needed before drawing conclusions about skill.`,
  };
}

export function fundGrowth(fund: Fund, currentNav: string | number) {
  return buildGrowthSnapshot(
    asNumber(fund.initial_cash),
    asNumber(currentNav),
    growthObjectiveFromMandate(fund),
  );
}

export function fundBrain(
  fundId: string,
  state: FundState,
  cycles: Cycle[],
  events: AuditEvent[],
): FundBrainSnapshot {
  return buildFundBrain(fundId, state, cycles, events);
}

/** Normalize a NAV series so the first point is 100. */
export function normalizeSeriesTo100(series: PerformancePoint[]): PerformancePoint[] {
  if (series.length === 0) return [];
  const base = series[0].value || series[0].nav || 1;
  if (base === 0) return series.map((p) => ({ ...p, value: 0 }));
  return series.map((p) => ({
    ...p,
    value: ((p.nav ?? p.value) / base) * 100,
  }));
}
