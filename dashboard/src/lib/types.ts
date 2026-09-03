/** Shared TypeScript contracts for the Edgecraft fund dashboard data layer. */

export type OrderSide = "buy" | "sell" | "short" | "cover" | "settle";
export type AssetClass = "stock" | "crypto" | "prediction" | string;
export type HypothesisStance = "long" | "short" | "exit" | string;
export type QuoteStatus = "open" | "settled" | string;

/** Row from the funds table. */
export interface Fund {
  fund_id: string;
  created_at: string;
  initial_cash: string;
  mandate_json: string;
  mandate?: Record<string, unknown>;
}

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

export interface Position {
  instrument_id: string;
  asset_class: AssetClass;
  quantity: string;
  average_entry: string;
  mark_price: string | null;
  market_value: string | null;
  unrealized_pnl: string | null;
}

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

export interface FundQuote {
  quote_id: string;
  instrument_id: string;
  asset_class: AssetClass;
  price: string;
  observed_at: string;
  source_timestamp: string;
  source_name: string;
  source_url: string;
  status: QuoteStatus;
}

export interface FundEvidence {
  evidence_id: string;
  observed_at: string;
  source_timestamp: string;
  source_name: string;
  source_url: string;
  claim: string;
  summary: string;
  instrument_ids: string[];
  content: string;
}

export interface FundOrder {
  instrument_id: string;
  asset_class: AssetClass;
  side: OrderSide;
  quantity: string;
  rationale: string;
  evidence_ids: string[];
}

export interface FundHypothesis {
  instrument_id: string;
  stance: HypothesisStance;
  statement: string;
  mechanism: string;
  catalysts: string[];
  falsifiers: string[];
  expected_horizon_hours: number;
  confidence: string;
  p_win?: string | null;
  playbook_id?: string | null;
  driver?: string | null;
  target_price: string | null;
  invalidation_price: string | null;
  evidence_ids: string[];
}

export interface DecisionJournal {
  market_regime: string;
  opportunity_set: string;
  portfolio_intent: string;
  what_changed: string;
  lessons_applied: string[];
  hypotheses: FundHypothesis[];
}

export interface RiskCheck {
  name: string;
  passed: boolean;
  observed: string;
  limit: string | null;
  detail: string;
}

export interface RiskEvaluation {
  approved: boolean;
  checks: RiskCheck[];
  order_count: number;
  turnover: string;
  pre_nav: string;
  post_nav: string;
  post_gross_exposure: string;
  post_net_exposure: string;
  post_short_exposure: string;
  post_drawdown: string;
  prediction_short_reserve: string;
}

export interface CycleRuntimeMetadata {
  edgecraft_version: string;
  mandate_digest: string;
  prompt_version: string | null;
  model: string | null;
  reasoning_effort: string | null;
  input_path: string | null;
  input_sha256: string | null;
  recorded_at: string | null;
}

export interface QuoteFreshnessRecord {
  instrument_id: string;
  quote_id: string;
  asset_class: AssetClass;
  status: QuoteStatus;
  price: string;
  observed_at: string;
  source_timestamp: string;
  observation_age_seconds: number;
  source_age_seconds: number;
  max_observation_age_seconds: number;
  max_source_age_seconds: number;
  source_name: string;
  source_url: string;
}

export interface CycleAudit {
  schema_version: string;
  runtime: CycleRuntimeMetadata | null;
  risk: RiskEvaluation | null;
  quote_freshness: QuoteFreshnessRecord[];
  fee_total: string;
  fill_count: number;
  settlement_count: number;
}

export interface Cycle {
  fund_id: string;
  cycle_key: string;
  decision_id: string;
  as_of: string;
  action: string;
  request_digest: string;
  created_at: string;
  decision: Record<string, unknown>;
  thesis: string;
  alternatives: string;
  risks: string;
  journal: DecisionJournal | null;
  evidence: FundEvidence[];
  orders: FundOrder[];
  quotes: FundQuote[];
  fills: Fill[];
  settlements: Fill[];
  state: FundState;
  result: Record<string, unknown>;
  audit: CycleAudit | null;
  decision_json?: string;
  quotes_json?: string;
  fills_json?: string;
  settlements_json?: string;
  state_json?: string;
  result_json?: string;
}

export interface PerformancePoint {
  as_of: string;
  value: number;
  nav?: number;
}

export interface TradeRow extends Fill {
  fund_id: string;
  cycle_key: string;
  as_of: string;
}

export interface SummaryMetrics {
  currentNav: number;
  cash: number;
  drawdown: number;
  peakNav: number;
  totalReturnPct: number;
  profitAndLoss: number;
  grossExposure: number;
  netExposure: number;
  shortExposure: number;
  realizedPnl: number;
  positionCount: number;
  fillCount: number;
  tradeCycleCount: number;
  holdCycleCount: number;
  cycleCount: number;
  tradeCount: number;
  initialCash: number;
}

export interface CycleListItem {
  fund_id: string;
  cycle_key: string;
  decision_id: string;
  as_of: string;
  action: string;
  created_at: string;
  nav: string | null;
  fill_count: number;
  order_count: number;
  thesis: string;
  what_changed: string | null;
  risk_approved: boolean | null;
  fee_total: string | null;
  decision_summary: {
    action: string;
    thesis_snippet: string;
  };
}

export type GrowthStage =
  | "bootstrap"
  | "compound"
  | "scale"
  | "protect"
  | "objective_reached";

export interface GrowthSnapshot {
  stage: GrowthStage;
  initialNav: number;
  currentNav: number;
  targetNav: number;
  targetHorizonYears: number;
  targetMultiple: number;
  remainingMultiple: number;
  simpleProgress: number;
  logProgress: number;
  requiredAnnualReturn: number;
  objectiveReached: boolean;
}

export interface PerformanceHistory {
  status: "measuring" | "active";
  initialCash: number;
  currentNav: number;
  profitAndLoss: number;
  totalReturn: number;
  maxDrawdown: number;
  positiveCycleCount: number;
  negativeCycleCount: number;
  holdCount: number;
  tradeCount: number;
  simulatedFillCount: number;
  interpretation: string;
}

export interface AuditEvent {
  sequence: number;
  event_type: string;
  occurred_at: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  event_hash: string;
}

export interface CycleMemory {
  cycle_key: string;
  as_of: string;
  action: string;
  thesis: string;
  what_changed: string | null;
  ending_nav: string;
  ending_position_count: number;
  fill_count: number;
  fee_total: string;
  next_cycle_nav_change: string | null;
  next_cycle_outcome: "pending" | "positive" | "negative" | "flat";
}

export interface FundActivityMemory {
  style: string;
  cash_nav_weight: number;
  open_position_count: number;
  consecutive_all_cash_holds: number;
  recent_trade_cycles: number;
  idle_cash: boolean;
}

export interface InstrumentMemory {
  instrument_id: string;
  asset_class: string;
  current_quantity: string;
  current_unrealized_pnl: string | null;
  simulated_fill_count: number;
  realized_exit_count: number;
  profitable_exit_count: number;
  losing_exit_count: number;
  realized_pnl: string;
  fees_paid: string;
  latest_hypothesis: FundHypothesis | null;
}

export interface RejectionMemory {
  cycle_key: string | null;
  reason: string;
  error_type: string;
}

export interface FundBrainSnapshot {
  schema_version: string;
  generated_at: string;
  fund_id: string;
  learning_boundary: string;
  recent_cycles: CycleMemory[];
  instruments: InstrumentMemory[];
  recent_rejections: RejectionMemory[];
  activity: FundActivityMemory;
  adaptive_prompts: string[];
}
