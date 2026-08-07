let meta = #{
    name: "build-fund-dashboard",
    description: "Build a Next.js shadcn PostHog/Linear-style fund dashboard over edgecraft-fund.db",
    when_to_use: "When you need a modern web UI to inspect paper-fund trades and compare performance vs S&P 500",
    phases: [
        #{ title: "Scaffold", detail: "Next.js app + shadcn + finance deps" },
        #{ title: "Data", detail: "SQLite fund DB access + API routes" },
        #{ title: "Shell", detail: "theme, layout, navigation" },
        #{ title: "Home", detail: "performance chart vs S&P 500" },
        #{ title: "Trades", detail: "all fills/cycles inspection page" },
        #{ title: "Verify", detail: "typecheck, build, fix blockers" },
    ],
};

let status_schema = #{
    "type": "object",
    "required": ["ok", "summary", "paths"],
    "properties": #{
        "ok": #{ "type": "boolean" },
        "summary": #{ "type": "string" },
        "paths": #{
            "type": "array",
            "maxItems": 40,
            "items": #{ "type": "string" },
        },
        "errors": #{
            "type": "array",
            "maxItems": 20,
            "items": #{ "type": "string" },
        },
    },
};

let app_dir = if args == () || args.app_dir == () { "dashboard" } else { args.app_dir };
let fund_db = if args == () || args.fund_db == () { "state/edgecraft-fund.db" } else { args.fund_db };

// ---------------------------------------------------------------------------
// Phase 1 — Scaffold Next.js + shadcn
// ---------------------------------------------------------------------------
phase("Scaffold");

let scaffold_prompt = "";
scaffold_prompt += "You are building Edgecraft Fund Dashboard in the git repo at the current workspace.\n";
scaffold_prompt += "GOAL: create a production-quality Next.js App Router app in directory: " + app_dir + "\n\n";
scaffold_prompt += "REQUIREMENTS:\n";
scaffold_prompt += "1. If " + app_dir + " already exists with package.json, do NOT recreate — inspect and only add missing pieces.\n";
scaffold_prompt += "2. Otherwise scaffold with non-interactive create-next-app:\n";
scaffold_prompt += "   npx create-next-app@latest " + app_dir + " --typescript --tailwind --eslint --app --src-dir --import-alias \"@/*\" --turbopack --use-npm --yes\n";
scaffold_prompt += "3. cd " + app_dir + " and init shadcn non-interactively:\n";
scaffold_prompt += "   npx shadcn@latest init -d --base radix\n";
scaffold_prompt += "4. Add shadcn components: button card table badge separator tabs input select dropdown-menu sheet skeleton tooltip scroll-area\n";
scaffold_prompt += "   npx shadcn@latest add button card table badge separator tabs input select dropdown-menu sheet skeleton tooltip scroll-area -y\n";
scaffold_prompt += "5. Install runtime deps: better-sqlite3 recharts date-fns lucide-react class-variance-authority clsx tailwind-merge\n";
scaffold_prompt += "6. Install types: npm i -D @types/better-sqlite3\n";
scaffold_prompt += "7. Create " + app_dir + "/.env.local with:\n";
scaffold_prompt += "   EDGECRAFT_FUND_DB=../" + fund_db + "\n";
scaffold_prompt += "8. Force dark mode default (html className dark) in root layout.\n";
scaffold_prompt += "9. Fix Geist font circular var if shadcn introduced it — use literal font family names in @theme inline.\n\n";
scaffold_prompt += "Do not create any placeholder business pages yet beyond a minimal home stub.\n";
scaffold_prompt += "Use shell commands; verify package.json and components/ui exist.\n";
scaffold_prompt += "Return ok=true only if " + app_dir + " builds package files and shadcn ui components are present.\n";

let scaffold = agent(scaffold_prompt, #{
    label: "scaffold-next-shadcn",
    capability_mode: "all",
    output_schema: status_schema,
});

if scaffold == () || !scaffold.success || scaffold.output.ok != true {
    let msg = "Scaffold failed";
    if scaffold != () && scaffold.output != () && scaffold.output.summary != () {
        msg = scaffold.output.summary;
    }
    complete(#{ ok: false, phase: "Scaffold", summary: msg });
}
log("Scaffold OK: " + scaffold.output.summary);

// ---------------------------------------------------------------------------
// Phase 2 — Data layer over SQLite fund DB
// ---------------------------------------------------------------------------
phase("Data");

let data_prompt = "";
data_prompt += "You are implementing the data/API layer for the Edgecraft fund dashboard.\n";
data_prompt += "App directory: " + app_dir + " (relative to repo root).\n";
data_prompt += "Source of truth DB: " + fund_db + " (SQLite). Env EDGECRAFT_FUND_DB points to it from the Next app.\n\n";
data_prompt += "READ the real schema first with shell sqlite3 or by reading src/edgecraft/paper_fund.py and docs/FUND_ACCOUNTING.md.\n";
data_prompt += "Tables: funds, cycles, events. Cycles store fills_json, state_json, decision_json, quotes_json as JSON text.\n";
data_prompt += "Decimals are stored as strings in JSON.\n\n";
data_prompt += "IMPLEMENT in " + app_dir + ":\n";
data_prompt += "1. src/lib/db.ts — open better-sqlite3 read-only, resolve path from process.env.EDGECRAFT_FUND_DB or default ../" + fund_db + " relative to process.cwd(). Use path.resolve. Set runtime nodejs only.\n";
data_prompt += "2. src/lib/types.ts — TypeScript types for Fund, Cycle, Fill, Position, FundState, PerformancePoint, TradeRow.\n";
data_prompt += "3. src/lib/fund.ts — pure helpers:\n";
data_prompt += "   - listFunds, getFund, listCycles(fundId), getLatestState\n";
data_prompt += "   - extractFillsFromCycles -> flat TradeRow[] with cycle_key, as_of, fill fields\n";
data_prompt += "   - buildNavSeries(fund, cycles) -> points starting at initial_cash at fund.created_at, then each cycle's state.nav at as_of\n";
data_prompt += "   - summaryMetrics(navSeries, positions) -> currentNav, cash, drawdown, peakNav, totalReturnPct, positionCount, tradeCount\n";
data_prompt += "4. src/lib/benchmark.ts — fetch SPY (S&P 500 proxy) daily closes from Yahoo chart API:\n";
data_prompt += "   https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&period1=UNIX&period2=UNIX\n";
data_prompt += "   Normalize both fund NAV and SPY to 100 at the fund start timestamp (first NAV point). Align SPY points to fund date range (from start to now). Cache in-memory with short TTL. On fetch failure, return null benchmark series and let UI degrade gracefully.\n";
data_prompt += "5. API routes (App Router, export const runtime = 'nodejs'):\n";
data_prompt += "   - GET /api/funds\n";
data_prompt += "   - GET /api/funds/[fundId]/n";
data_prompt += "   - GET /api/funds/[fundId]/performance  -> { fundSeries, benchmarkSeries, metrics, positions }\n";
data_prompt += "   - GET /api/funds/[fundId]/trades -> all fills as TradeRow[], plus cycle metadata\n";
data_prompt += "   - GET /api/funds/[fundId]/cycles -> cycles with parsed decision summary (action, thesis snippet)\n";
data_prompt += "6. Never mutate the DB. Open with better-sqlite3 readonly: true if supported, else never run writes.\n\n";
data_prompt += "Verify by running a small node/tsx script or curling after next start is NOT required — instead write a tiny node -e using better-sqlite3 that prints cycle count.\n";
data_prompt += "Return paths of all created files and ok=true if the module can open the DB and list cycles.\n";

let data = agent(data_prompt, #{
    label: "data-layer",
    capability_mode: "all",
    output_schema: status_schema,
});

if data == () || !data.success || data.output.ok != true {
    let msg = "Data layer failed";
    if data != () && data.output != () && data.output.summary != () {
        msg = data.output.summary;
    }
    complete(#{ ok: false, phase: "Data", summary: msg });
}
log("Data OK: " + data.output.summary);

// ---------------------------------------------------------------------------
// Phase 3 — Shell: PostHog/Linear finance theme
// ---------------------------------------------------------------------------
phase("Shell");

let shell_prompt = "";
shell_prompt += "Design and implement the app shell and visual system for Edgecraft dashboard in " + app_dir + ".\n\n";
shell_prompt += "AESTHETIC BRIEF (must follow):\n";
shell_prompt += "- PostHog + Linear product aesthetic: dark-first, ultra-clean, high-signal finance tool.\n";
shell_prompt += "- Background near #0b0c0f / zinc-950; elevated surfaces #12141a; hairline borders white/5–10%.\n";
shell_prompt += "- Accent: Linear-like indigo/violet (oklch ~0.62 0.2 275) for primary actions and chart fund series.\n";
shell_prompt += "- Positive P&L: emerald; negative: rose. Muted labels zinc-400.\n";
shell_prompt += "- Typography: Geist Sans UI + Geist Mono for numbers, IDs, timestamps, NAV.\n";
shell_prompt += "- Density: compact dashboard (gap-4, text-sm), generous page padding, no glassmorphism spam.\n";
shell_prompt += "- Signature: left rail nav with tiny brand mark 'EC', page titles with mono micro-labels (e.g. PERFORMANCE).\n";
shell_prompt += "- Avoid generic AI-slop gradients, large hero blobs, and over-carding.\n\n";
shell_prompt += "IMPLEMENT:\n";
shell_prompt += "1. Update globals.css theme tokens for the palette above (dark default).\n";
shell_prompt += "2. src/components/app-shell.tsx — top bar + left sidebar: Overview (/), Trades (/trades). Active state subtle.\n";
shell_prompt += "3. src/components/stat-card.tsx — compact metric tile (label, mono value, optional delta).\n";
shell_prompt += "4. src/components/format.ts — formatUsd, formatPct, formatQty, formatTs using Intl; never use raw float noise for money display (cap decimals).\n";
shell_prompt += "5. Root layout: dark class, TooltipProvider, AppShell wrapping children, metadata title 'Edgecraft Fund'.\n";
shell_prompt += "6. Keep mobile usable: sidebar collapses to top tabs or sheet if needed.\n\n";
shell_prompt += "Do not implement full chart/trades tables yet if missing — leave clear slot areas.\n";
shell_prompt += "Return ok=true and paths changed.\n";

let shell = agent(shell_prompt, #{
    label: "app-shell-theme",
    capability_mode: "all",
    output_schema: status_schema,
});

if shell == () || !shell.success || shell.output.ok != true {
    let msg = "Shell failed";
    if shell != () && shell.output != () && shell.output.summary != () {
        msg = shell.output.summary;
    }
    complete(#{ ok: false, phase: "Shell", summary: msg });
}
log("Shell OK: " + shell.output.summary);

// ---------------------------------------------------------------------------
// Phase 4 — Home performance chart
// ---------------------------------------------------------------------------
phase("Home");

let home_prompt = "";
home_prompt += "Implement the home/overview page for Edgecraft dashboard in " + app_dir + ".\n\n";
home_prompt += "PAGE: src/app/page.tsx (server component preferred; client chart as child).\n";
home_prompt += "Data: call lib/fund + lib/benchmark server-side (or fetch /api/funds/{id}/performance). Default fund: first fund in DB (edgecraft-1k).\n\n";
home_prompt += "UI REQUIREMENTS:\n";
home_prompt += "1. Header: fund id, 'Paper fund · $1,000 bankroll', last as_of.\n";
home_prompt += "2. Stat row: NAV, Cash, Total return %, Drawdown, Gross exposure, Open positions, Trade count.\n";
home_prompt += "3. Main chart card title: 'Fund vs S&P 500' with subtitle that SPY is the proxy, both normalized to 100 at fund inception.\n";
home_prompt += "4. Chart component src/components/performance-chart.tsx using recharts:\n";
home_prompt += "   - dual line: Edgecraft (indigo) and S&P 500 / SPY (zinc muted)\n";
home_prompt += "   - dark tooltip, mono axis ticks, no chart junk, responsive container height ~360px\n";
home_prompt += "   - optional area under fund line at very low opacity\n";
home_prompt += "5. Secondary card: current positions table (instrument, class, qty, avg entry, mark, mkt value, unrealized).\n";
home_prompt += "6. Empty/degraded states: if only one NAV point, still show chart with inception + latest; if benchmark fails, show fund-only with banner.\n";
home_prompt += "7. Make numbers beautiful and scannable — tabular nums via font-mono.\n\n";
home_prompt += "Wire real data from SQLite. No fake hard-coded trades.\n";
home_prompt += "Return ok=true after the page compiles conceptually and files exist.\n";

let home = agent(home_prompt, #{
    label: "home-performance",
    capability_mode: "all",
    output_schema: status_schema,
});

if home == () || !home.success || home.output.ok != true {
    let msg = "Home page failed";
    if home != () && home.output != () && home.output.summary != () {
        msg = home.output.summary;
    }
    complete(#{ ok: false, phase: "Home", summary: msg });
}
log("Home OK: " + home.output.summary);

// ---------------------------------------------------------------------------
// Phase 5 — Trades inspection page
// ---------------------------------------------------------------------------
phase("Trades");

let trades_prompt = "";
trades_prompt += "Implement the trades inspection page for Edgecraft dashboard in " + app_dir + ".\n\n";
trades_prompt += "PAGE: src/app/trades/page.tsx\n";
trades_prompt += "Data from lib/fund extractFillsFromCycles + cycles decision metadata.\n\n";
trades_prompt += "UI REQUIREMENTS:\n";
trades_prompt += "1. Page title 'Trades' with mono micro-label ALL FILLS.\n";
trades_prompt += "2. Toolbar filters (client component ok): search instrument, side multi (buy/sell/short/cover), asset class, cycle key.\n";
trades_prompt += "3. Dense shadcn Table of every fill across all cycles:\n";
trades_prompt += "   columns: as_of, cycle_key, instrument_id, asset_class, side (badge color), quantity, execution_price, gross_notional, fee, realized_pnl, cash_delta, fill_id (truncated mono).\n";
trades_prompt += "4. Summary chips above table: total fills, buys, sells, shorts, covers, total fees, realized pnl sum.\n";
trades_prompt += "5. Expandable row or side sheet with full fill JSON + parent cycle action/thesis if available.\n";
trades_prompt += "6. Cycles section or tab: list cycles with action, as_of, nav after, fill count — click filters trades.\n";
trades_prompt += "7. Empty state if no fills yet.\n";
trades_prompt += "8. Sort default newest first.\n\n";
trades_prompt += "Read-only wrapper around DB — no mutations. Match the app shell theme.\n";
trades_prompt += "Return ok=true and key paths.\n";

let trades = agent(trades_prompt, #{
    label: "trades-page",
    capability_mode: "all",
    output_schema: status_schema,
});

if trades == () || !trades.success || trades.output.ok != true {
    let msg = "Trades page failed";
    if trades != () && trades.output != () && trades.output.summary != () {
        msg = trades.output.summary;
    }
    complete(#{ ok: false, phase: "Trades", summary: msg });
}
log("Trades OK: " + trades.output.summary);

// ---------------------------------------------------------------------------
// Phase 6 — Verify build and fix
// ---------------------------------------------------------------------------
phase("Verify");

let verify_prompt = "";
verify_prompt += "Verify and fix the Edgecraft dashboard in " + app_dir + " until it typechecks and builds.\n\n";
verify_prompt += "STEPS:\n";
verify_prompt += "1. cd " + app_dir + " && npm run build\n";
verify_prompt += "2. Fix any TypeScript, import, or Next.js errors. Prefer nodejs runtime for API routes using better-sqlite3.\n";
verify_prompt += "3. Ensure .env.local has EDGECRAFT_FUND_DB=../" + fund_db + "\n";
verify_prompt += "4. Add " + app_dir + "/README.md with: npm install, npm run dev, env var, pages overview.\n";
verify_prompt += "5. Optionally add a root Makefile target or note in repo README — only a short 'Dashboard' section in main README if it exists and is short to update.\n";
verify_prompt += "6. Smoke: node script that imports nothing from next but uses better-sqlite3 to confirm DB path from env default resolves and prints fund_id + cycle count + fill count.\n";
verify_prompt += "7. Do not commit git unless asked.\n\n";
verify_prompt += "Return ok=true only if npm run build succeeds. Include build errors in errors[] if not.\n";

let verify = agent(verify_prompt, #{
    label: "verify-build",
    capability_mode: "all",
    output_schema: status_schema,
});

if verify == () || !verify.success || verify.output.ok != true {
    // One repair pass
    log("Verify failed — running repair pass");
    let repair_prompt = "";
    repair_prompt += "The dashboard in " + app_dir + " failed verification. Fix until npm run build passes.\n";
    if verify != () && verify.output != () {
        if verify.output.summary != () {
            repair_prompt += "Summary: " + verify.output.summary + "\n";
        }
        if verify.output.errors != () {
            repair_prompt += "Errors JSON: " + json_encode(verify.output.errors) + "\n";
        }
    }
    repair_prompt += "Read build logs by running npm run build yourself. Fix root causes only. Return ok=true iff build succeeds.\n";

    let repair = agent(repair_prompt, #{
        label: "repair-build",
        capability_mode: "all",
        output_schema: status_schema,
    });

    if repair == () || !repair.success || repair.output.ok != true {
        let msg = "Build verification failed after repair";
        if repair != () && repair.output != () && repair.output.summary != () {
            msg = repair.output.summary;
        }
        complete(#{
            ok: false,
            phase: "Verify",
            summary: msg,
            app_dir: app_dir,
        });
    }
    log("Repair OK: " + repair.output.summary);
} else {
    log("Verify OK: " + verify.output.summary);
}

// Final report
let report = "";
report += "# Edgecraft Fund Dashboard\n\n";
report += "Built end-to-end under `" + app_dir + "`.\n\n";
report += "## Run\n\n";
report += "```bash\ncd " + app_dir + "\nnpm install\nnpm run dev\n```\n\n";
report += "Open http://localhost:3000 — Overview chart (fund vs S&P 500 / SPY).\n";
report += "Open http://localhost:3000/trades — all fills from `" + fund_db + "`.\n\n";
report += "## Data\n\n";
report += "Read-only SQLite via `EDGECRAFT_FUND_DB` (default `../" + fund_db + "`).\n";
report += "No broker mutations; paper fund only.\n";

let path = write_scratch_file("dashboard-report.md", report);

complete(#{
    ok: true,
    app_dir: app_dir,
    fund_db: fund_db,
    summary: "Dashboard built in " + app_dir + " with performance vs S&P and trades inspector",
    report_path: path,
    run: "cd " + app_dir + " && npm run dev",
});
