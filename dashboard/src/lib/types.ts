/** Shared TypeScript contracts for the Edgecraft fund dashboard data layer. */

export type OrderSide = "buy" | "sell" | "short" | "cover" | "settle";
export type AssetClass = "stock" | "crypto" | "prediction" | string;
export type DecisionAction = "trade" | "hold" | string;

/** Row from the funds table. */
export interface Fund {
  fund_id: string;
  created_at: string;
  initial_cash: string;
  mandate_json: string;
  /** Parsed mandate when available; decimals remain as strings. */
  mandate?: Record<string, unknown>;
}

/** Simulated fill / settlement from fills_json (decimals as strings). */
export interface Fill {
  fill_id: string;
  instrument_id: string;
  asset_class: AssetClass;
  side: OrderSide;
  quantity: string;
  quote_price: string;
  execution_price: string;
  gross_notional: string;
  fee: string;
  cash_delta: string;
  realized_pnl: string;
  quote_id: string;
  is_settlement: boolean;
}

/** Open position from state_json.positions (decimals as strings). */
export interface Position {
  instrument_id: string;
  asset_class: AssetClass;
  quantity: string;
  average_entry: string;
  mark_price: string | null;
  market_value: string | null;
  unrealized_pnl: string | null;
}

/** Point-in-time fund state from state_json. */
export interface FundState {
  fund_id: string;
  as_of: string;
  cash: string;
  positions: Position[];
  nav: string;
  peak_nav: string;
  drawdown: string;
  gross_exposure: string;
  net_exposure: string;
  short_exposure: string;
  realized_pnl_cumulative: string;
  cycle_count: number;
  last_cycle_key: string | null;
}

/** Decision payload subset used by the UI. */
export interface DecisionSummary {
  decision_id?: string;
  action: DecisionAction;
  thesis: string;
  alternatives?: string;
  risks?: string;
  order_count?: number;
}

/** Full cycle row with JSON columns parsed for convenience. */
export interface Cycle {
  fund_id: string;
  cycle_key: string;
  decision_id: string;
  as_of: string;
  action: string;
  request_digest: string;
  created_at: string;
  decision: Record<string, unknown>;
  quotes: unknown[];
  fills: Fill[];
  settlements: unknown[];
  state: FundState;
  result: Record<string, unknown>;
  /** Raw JSON text retained for audit if needed. */
  decision_json?: string;
  quotes_json?: string;
  fills_json?: string;
  settlements_json?: string;
  state_json?: string;
  result_json?: string;
}

/** NAV time series point for charts (normalized or absolute). */
export interface PerformancePoint {
  as_of: string;
  /** Absolute NAV or normalized index (e.g. 100 at start). */
  value: number;
  /** Absolute fund NAV when this is a fund series point. */
  nav?: number;
}

/** Flattened trade row for the trades table. */
export interface TradeRow extends Fill {
  fund_id: string;
  cycle_key: string;
  as_of: string;
}

/** Summary metrics for the fund header cards. */
export interface SummaryMetrics {
  currentNav: number;
  cash: number;
  drawdown: number;
  peakNav: number;
  totalReturnPct: number;
  positionCount: number;
  tradeCount: number;
  initialCash: number;
}

/** Cycle list item with a short decision summary for the cycles view. */
export interface CycleListItem {
  fund_id: string;
  cycle_key: string;
  decision_id: string;
  as_of: string;
  action: string;
  created_at: string;
  nav: string | null;
  fill_count: number;
  decision_summary: {
    action: string;
    thesis_snippet: string;
  };
}
