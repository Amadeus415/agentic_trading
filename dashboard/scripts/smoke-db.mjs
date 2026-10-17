/**
 * Smoke: resolve fund DB path (env or default) with better-sqlite3 only.
 * Does not import Next.js. Run from dashboard/: node scripts/smoke-db.mjs
 */
import Database from "better-sqlite3";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dashboardRoot = path.resolve(__dirname, "..");

const DEFAULT_RELATIVE_DB = path.join("..", "state", "edgecraft-aggressive.db");

function resolveFundDbPath() {
  const fromEnv = process.env.EDGECRAFT_FUND_DB?.trim();
  if (fromEnv) {
    return path.isAbsolute(fromEnv)
      ? fromEnv
      : path.resolve(process.cwd(), fromEnv);
  }
  // Match src/lib/db.ts: cwd-relative default (typically dashboard/).
  return path.resolve(process.cwd(), DEFAULT_RELATIVE_DB);
}

const dbPath = resolveFundDbPath();
console.log("db_path:", dbPath);
console.log("cwd:", process.cwd());
console.log("dashboard_root:", dashboardRoot);

const db = new Database(dbPath, { readonly: true, fileMustExist: true });
db.pragma("query_only = ON");

const funds = db.prepare("SELECT fund_id FROM funds ORDER BY created_at").all();
if (funds.length === 0) {
  console.log("fund_id: (none)");
  console.log("cycle_count: 0");
  console.log("fill_count: 0");
  db.close();
  process.exit(0);
}

for (const fund of funds) {
  const fundId = fund.fund_id;
  const cycleCount = db.prepare("SELECT COUNT(*) AS n FROM cycles WHERE fund_id = ?").get(fundId).n;
  const fillRows = db.prepare("SELECT fills_json FROM cycles WHERE fund_id = ?").all(fundId);
  const fillCount = fillRows.reduce((count, row) => count + JSON.parse(row.fills_json).length, 0);
  console.log(JSON.stringify({ fund_id: fundId, cycle_count: cycleCount, fill_count: fillCount }));
}
if (db.pragma("query_only", { simple: true }) !== 1) throw new Error("DB must be query-only");
db.close();
