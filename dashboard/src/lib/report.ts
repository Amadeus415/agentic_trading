/** Read the Python-generated attribution report without reimplementing fund math. */
import fs from "node:fs";
import path from "node:path";

import { resolveFundDbPath } from "./db";

export type FundReport = {
  fund_id: string;
  generated_at: string;
  lineage?: { segments: Array<{ revision: string; basis: string; commit: string; cycles: number; nav_change: string; fees: string }> };
  prediction_scores?: { summary: { contracts: number; model_brier: string | null; market_brier: string | null; brier_improvement: string | null; sampled_clv: string | null; model_brier_count: number; sampled_clv_count: number }; interpretation: string };
  forecast_skill?: ForecastSkill;
  review?: {
    due: boolean;
    next_review_at: string;
    closed_trades_since_review: number;
    trade_threshold: number;
    completed_reviews: number;
  };
  playbook_statuses?: Record<string, string>;
  summary: {
    closed_trades: number;
    hit_rate: string | null;
    expectancy_after_cost: string | null;
    profit_factor: string | null;
    hypotheses: number;
  };
  calibration: Array<{
    bucket: string;
    count: number;
    mean_stated_p_win: string;
    realized_win_rate: string;
    calibration_error: string;
  }>;
  round_trips: Array<{
    instrument_id: string;
    side: string;
    playbook_id: string;
    closed_at: string;
    realized_pnl_after_cost: string;
  }>;
};

export type VariantSkill = {
  forecasts: number;
  resolved: number;
  skill: number | null;
  drift_observed: number;
  mean_drift_toward_forecast: number | null;
  trust_basis: "prior" | "resolution" | "drift";
  trust: number;
};

export type ForecastSkill = {
  summary: VariantSkill;
  variants: Record<string, VariantSkill>;
  categories: Record<string, VariantSkill>;
  head_to_head: Array<{ left: string; right: string; shared_resolved: number; left_advantage: number }>;
  favorite_bias: { observed: number; resolved: number; fitted_gamma: number | null; gamma: number; prior_gamma: number };
  interpretation: string;
};

export function readFundReport(fundId: string): FundReport | null {
  const directory = path.dirname(resolveFundDbPath());
  const configured = process.env.EDGECRAFT_FUND_REPORT?.trim();
  const paths = configured ? [configured] : [
    path.join(directory, `fund-report-${fundId.replace(/[^a-zA-Z0-9_-]/g, "_")}.json`),
    path.join(directory, "fund-report.json"),
  ];
  for (const reportPath of paths) {
    try {
      const report = JSON.parse(fs.readFileSync(/* turbopackIgnore: true */ reportPath, "utf8")) as FundReport;
      if (report.fund_id === fundId) return report;
    } catch { /* Report may not have been generated for this fund. */ }
  }
  return null;
}
