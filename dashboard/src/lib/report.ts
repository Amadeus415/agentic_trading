/** Read the Python-generated attribution report without reimplementing fund math. */
import fs from "node:fs";
import path from "node:path";

import { resolveFundDbPath } from "./db";

export type FundReport = {
  fund_id: string;
  generated_at: string;
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
  const reportPath = path.join(path.dirname(resolveFundDbPath()), "fund-report.json");
  try {
    return JSON.parse(fs.readFileSync(reportPath, "utf8")) as FundReport;
  } catch {
    return null;
  }
}
