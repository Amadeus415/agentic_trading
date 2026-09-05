/** Read the Python-generated attribution report without reimplementing fund math. */
import fs from "node:fs";
import path from "node:path";

import { resolveFundDbPath } from "./db";

export type FundReport = {
  fund_id: string;
  generated_at: string;
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

export function readFundReport(): FundReport | null {
  const reportPath = process.env.EDGECRAFT_FUND_REPORT?.trim() || path.join(path.dirname(resolveFundDbPath()), "fund-report.json");
  try {
    // Local runtime data must be read at request time, never bundled into a release.
    return JSON.parse(fs.readFileSync(/* turbopackIgnore: true */ reportPath, "utf8")) as FundReport;
  } catch {
    return null;
  }
}
