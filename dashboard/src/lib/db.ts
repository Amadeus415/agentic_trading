/**
 * Read-only SQLite access to the Edgecraft paper-fund ledger.
 * Node.js runtime only — never import from client components / edge.
 */
import Database from "better-sqlite3";
import path from "path";

const DEFAULT_RELATIVE_DB = path.join("..", "state", "edgecraft-aggressive.db");

let cached: Database.Database | null = null;
let cachedPath: string | null = null;

/** Resolve the fund DB path from EDGECRAFT_FUND_DB or the repo state default. */
export function resolveFundDbPath(): string {
  const fromEnv = process.env.EDGECRAFT_FUND_DB?.trim();
  if (fromEnv) {
    return path.resolve(fromEnv);
  }
  return path.resolve(process.cwd(), DEFAULT_RELATIVE_DB);
}

/**
 * Open (or reuse) a read-only better-sqlite3 connection.
 * Never mutates the database.
 */
export function getDb(): Database.Database {
  const dbPath = resolveFundDbPath();
  if (cached && cachedPath === dbPath) {
    return cached;
  }
  if (cached) {
    try {
      cached.close();
    } catch {
      // ignore close errors on path switch
    }
    cached = null;
  }

  const db = new Database(dbPath, {
    readonly: true,
    fileMustExist: true,
  });
  // Defensive: refuse writes even if a caller forgets readonly.
  db.pragma("query_only = ON");

  cached = db;
  cachedPath = dbPath;
  return db;
}
