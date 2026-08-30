/**
 * Compact ledger-derived brain for the dashboard.
 * Mirrors src/edgecraft/fund_brain.py without mutating state.
 */
import { asNumber } from "./numbers";
import type {
  AuditEvent,
  Cycle,
  CycleMemory,
  Fill,
  FundActivityMemory,
  FundBrainSnapshot,
  FundHypothesis,
  FundState,
  InstrumentMemory,
  RejectionMemory,
} from "./types";

const LEARNING_BOUNDARY =
  "Next-cycle NAV direction includes intervening marks, costs, and portfolio changes; " +
  "it is feedback, not causal attribution or proof of skill.";

type InstrumentRow = {
  instrument_id: string;
  asset_class: string;
  current_quantity: string;
  current_unrealized_pnl: string | null;
  simulated_fill_count: number;
  realized_exit_count: number;
  profitable_exit_count: number;
  losing_exit_count: number;
  realized_pnl: number;
  fees_paid: number;
  latest_hypothesis: FundHypothesis | null;
};

function emptyInstrument(instrumentId: string): InstrumentRow {
  return {
    instrument_id: instrumentId,
    asset_class: "unknown",
    current_quantity: "0",
    current_unrealized_pnl: null,
    simulated_fill_count: 0,
    realized_exit_count: 0,
    profitable_exit_count: 0,
    losing_exit_count: 0,
    realized_pnl: 0,
    fees_paid: 0,
    latest_hypothesis: null,
  };
}

function addFill(row: InstrumentRow, fill: Fill): void {
  row.asset_class = fill.asset_class || row.asset_class;
  row.simulated_fill_count += 1;
  const realized = asNumber(fill.realized_pnl);
  row.realized_pnl += realized;
  row.fees_paid += asNumber(fill.fee);
  if (fill.side === "sell" || fill.side === "cover" || fill.side === "settle") {
    row.realized_exit_count += 1;
    if (realized > 0) row.profitable_exit_count += 1;
    else if (realized < 0) row.losing_exit_count += 1;
  }
}

export function buildFundBrain(
  fundId: string,
  state: FundState,
  cycles: Cycle[],
  events: AuditEvent[],
  options?: {
    generatedAt?: string;
    cycleLimit?: number;
    instrumentLimit?: number;
    rejectionLimit?: number;
  },
): FundBrainSnapshot {
  const cycleLimit = options?.cycleLimit ?? 8;
  const instrumentLimit = options?.instrumentLimit ?? 40;
  const rejectionLimit = options?.rejectionLimit ?? 5;

  const currentPositions = new Map(
    (state.positions ?? []).map((p) => [p.instrument_id, p] as const),
  );
  const instrumentRows = new Map<string, InstrumentRow>();
  const lastActivity = new Map<string, number>();
  const cycleMemories: CycleMemory[] = [];

  for (let index = 0; index < cycles.length; index++) {
    const cycle = cycles[index];
    for (const hypothesis of cycle.journal?.hypotheses ?? []) {
      const row =
        instrumentRows.get(hypothesis.instrument_id) ??
        emptyInstrument(hypothesis.instrument_id);
      row.latest_hypothesis = hypothesis;
      instrumentRows.set(hypothesis.instrument_id, row);
      lastActivity.set(hypothesis.instrument_id, index);
    }

    const fills = [...(cycle.fills ?? []), ...(cycle.settlements ?? [])];
    for (const fill of fills) {
      const row =
        instrumentRows.get(fill.instrument_id) ??
        emptyInstrument(fill.instrument_id);
      addFill(row, fill);
      instrumentRows.set(fill.instrument_id, row);
      lastActivity.set(fill.instrument_id, index);
    }

    const endingNav = asNumber(cycle.state?.nav);
    let nextChange: number | null = null;
    let outcome: CycleMemory["next_cycle_outcome"] = "pending";
    if (index + 1 < cycles.length) {
      const nextNav = asNumber(cycles[index + 1].state?.nav);
      nextChange = nextNav - endingNav;
      outcome =
        nextChange > 0 ? "positive" : nextChange < 0 ? "negative" : "flat";
    }

    cycleMemories.push({
      cycle_key: cycle.cycle_key,
      as_of: cycle.as_of,
      action: cycle.action,
      thesis: cycle.thesis,
      what_changed: cycle.journal?.what_changed ?? null,
      ending_nav: cycle.state?.nav ?? "0",
      ending_position_count: cycle.state?.positions?.length ?? 0,
      fill_count: fills.length,
      fee_total: cycle.audit?.fee_total ?? "0",
      next_cycle_nav_change:
        nextChange === null ? null : String(nextChange),
      next_cycle_outcome: outcome,
    });
  }

  for (const [instrumentId, position] of currentPositions) {
    const row = instrumentRows.get(instrumentId) ?? emptyInstrument(instrumentId);
    row.asset_class = position.asset_class || row.asset_class;
    row.current_quantity = position.quantity;
    row.current_unrealized_pnl = position.unrealized_pnl;
    instrumentRows.set(instrumentId, row);
    if (!lastActivity.has(instrumentId)) {
      lastActivity.set(instrumentId, cycles.length);
    }
  }

  const ranked = [...instrumentRows.keys()]
    .sort((a, b) => {
      const aOpen = currentPositions.has(a) ? 0 : 1;
      const bOpen = currentPositions.has(b) ? 0 : 1;
      if (aOpen !== bOpen) return aOpen - bOpen;
      const act = (lastActivity.get(b) ?? -1) - (lastActivity.get(a) ?? -1);
      if (act !== 0) return act;
      return a.localeCompare(b);
    })
    .slice(0, instrumentLimit);

  const instruments: InstrumentMemory[] = ranked.map((id) => {
    const row = instrumentRows.get(id)!;
    return {
      instrument_id: row.instrument_id,
      asset_class: row.asset_class,
      current_quantity: row.current_quantity,
      current_unrealized_pnl: row.current_unrealized_pnl,
      simulated_fill_count: row.simulated_fill_count,
      realized_exit_count: row.realized_exit_count,
      profitable_exit_count: row.profitable_exit_count,
      losing_exit_count: row.losing_exit_count,
      realized_pnl: String(row.realized_pnl),
      fees_paid: String(row.fees_paid),
      latest_hypothesis: row.latest_hypothesis,
    };
  });

  const rejections: RejectionMemory[] = events
    .filter((event) => event.event_type === "cycle_rejected")
    .map((event) => ({
      cycle_key:
        event.payload.cycle_key == null
          ? null
          : String(event.payload.cycle_key),
      reason: String(event.payload.reason ?? "unknown rejection"),
      error_type: String(event.payload.error_type ?? "PaperFundError"),
    }))
    .slice(-rejectionLimit);

  const recent = cycleMemories.slice(-cycleLimit);
  const activity = activityMemory(state, recent);

  return {
    schema_version: "edgecraft.fund-brain.v1",
    generated_at: options?.generatedAt ?? new Date().toISOString(),
    fund_id: fundId,
    learning_boundary: LEARNING_BOUNDARY,
    recent_cycles: recent,
    instruments,
    recent_rejections: rejections,
    activity,
    adaptive_prompts: adaptivePrompts(instruments, rejections, activity),
  };
}

function activityMemory(
  state: FundState,
  recentCycles: CycleMemory[],
): FundActivityMemory {
  const nav = asNumber(state.nav);
  const cashWeight = nav === 0 ? 1 : asNumber(state.cash) / nav;
  let consecutive = 0;
  for (let i = recentCycles.length - 1; i >= 0; i--) {
    const item = recentCycles[i];
    if (item.action === "hold" && item.ending_position_count === 0) {
      consecutive += 1;
      continue;
    }
    break;
  }
  return {
    style: "short_term_active",
    cash_nav_weight: cashWeight,
    open_position_count: state.positions.filter((p) => asNumber(p.quantity) !== 0)
      .length,
    consecutive_all_cash_holds: consecutive,
    recent_trade_cycles: recentCycles.filter((item) => item.action === "trade")
      .length,
    idle_cash: state.positions.filter((p) => asNumber(p.quantity) !== 0).length === 0,
  };
}

function adaptivePrompts(
  instruments: InstrumentMemory[],
  rejections: RejectionMemory[],
  activity: FundActivityMemory,
): string[] {
  const prompts = [
    "This is a short-term active book: express researched 4-72h views with orders.",
    "A sourced catalyst, target, invalidation, and size is a valid thesis; lack of a calibrated probability model is not a hold reason.",
    "U.S. cash-equity close is not a reason to stay in cash; native crypto and prediction markets remain in scope.",
    "Re-test every open position against its current falsifiers before adding risk.",
    "Compare new opportunities with the opportunity cost of every existing position.",
  ];
  if (activity.idle_cash) {
    prompts.unshift(
      "The book is 100% cash. A scheduled hold will be rejected. Submit researched short-term buy/sell/short/cover orders with fresh quotes.",
    );
    if (activity.consecutive_all_cash_holds) {
      prompts.splice(
        1,
        0,
        `The last ${activity.consecutive_all_cash_holds} completed cycle(s) were all-cash holds. Idle cash is a process miss, not prudence.`,
      );
    }
  }
  const losing = instruments
    .filter((item) => item.losing_exit_count > 0)
    .map((item) => item.instrument_id);
  if (losing.length > 0) {
    prompts.push(
      "Review whether the mechanisms or sizing failed on prior losing exits: " +
        losing.slice(0, 8).join(", ") +
        ".",
    );
  }
  const underwater = instruments
    .filter((item) => asNumber(item.current_unrealized_pnl) < 0)
    .map((item) => item.instrument_id);
  if (underwater.length > 0) {
    prompts.push(
      "Explicitly keep, reduce, or exit currently underwater hypotheses: " +
        underwater.slice(0, 8).join(", ") +
        ".",
    );
  }
  if (rejections.length > 0) {
    prompts.push(
      "Do not bypass prior rejected gates; fix the research or portfolio plan upstream.",
    );
  }
  return prompts;
}
