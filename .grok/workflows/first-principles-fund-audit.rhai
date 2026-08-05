let meta = #{
    name: "first-principles-fund-audit",
    description: "First-principles audit then improve Edgecraft into a healthy agentic autonomous trading fund",
    when_to_use: "When the repo needs a full health audit, deletion of unnecessary process, and modernization for autonomous trading",
    phases: [
        #{ title: "Map", detail: "inventory architecture and operational surface" },
        #{ title: "Audit", detail: "parallel first-principles review across dimensions" },
        #{ title: "Plan", detail: "delete first, then simplify, then build only what is required" },
        #{ title: "Delete", detail: "remove dead weight and unnecessary process" },
        #{ title: "Simplify", detail: "coalesce modules and clarify the autonomy path" },
        #{ title: "Build", detail: "close gaps that block agentic autonomous trading" },
        #{ title: "Verify", detail: "tests, adversarial review, final report" },
    ],
};

// Structured outputs ---------------------------------------------------------

let map_schema = #{
    "type": "object",
    "required": ["core_loop", "modules", "entrypoints", "risks", "notes"],
    "properties": #{
        "core_loop": #{ "type": "string" },
        "modules": #{
            "type": "array",
            "maxItems": 40,
            "items": #{
                "type": "object",
                "required": ["path", "role", "lines_approx", "keep_or_question"],
                "properties": #{
                    "path": #{ "type": "string" },
                    "role": #{ "type": "string" },
                    "lines_approx": #{ "type": "integer" },
                    "keep_or_question": #{ "type": "string" },
                },
            },
        },
        "entrypoints": #{ "type": "array", "maxItems": 20, "items": #{ "type": "string" } },
        "risks": #{ "type": "array", "maxItems": 15, "items": #{ "type": "string" } },
        "notes": #{ "type": "string" },
    },
};

let audit_schema = #{
    "type": "object",
    "required": ["dimension", "summary", "findings"],
    "properties": #{
        "dimension": #{ "type": "string" },
        "summary": #{ "type": "string" },
        "findings": #{
            "type": "array",
            "maxItems": 12,
            "items": #{
                "type": "object",
                "required": ["severity", "title", "evidence", "action", "rationale"],
                "properties": #{
                    "severity": #{ "type": "string" },
                    "title": #{ "type": "string" },
                    "evidence": #{ "type": "string" },
                    "action": #{ "type": "string" },
                    "rationale": #{ "type": "string" },
                    "paths": #{
                        "type": "array",
                        "maxItems": 12,
                        "items": #{ "type": "string" },
                    },
                },
            },
        },
    },
};

let plan_schema = #{
    "type": "object",
    "required": ["thesis", "delete", "simplify", "build", "do_not_touch", "success_criteria"],
    "properties": #{
        "thesis": #{ "type": "string" },
        "delete": #{
            "type": "array",
            "maxItems": 12,
            "items": #{
                "type": "object",
                "required": ["id", "title", "paths", "why", "risk"],
                "properties": #{
                    "id": #{ "type": "string" },
                    "title": #{ "type": "string" },
                    "paths": #{ "type": "array", "maxItems": 20, "items": #{ "type": "string" } },
                    "why": #{ "type": "string" },
                    "risk": #{ "type": "string" },
                },
            },
        },
        "simplify": #{
            "type": "array",
            "maxItems": 12,
            "items": #{
                "type": "object",
                "required": ["id", "title", "paths", "why", "approach"],
                "properties": #{
                    "id": #{ "type": "string" },
                    "title": #{ "type": "string" },
                    "paths": #{ "type": "array", "maxItems": 20, "items": #{ "type": "string" } },
                    "why": #{ "type": "string" },
                    "approach": #{ "type": "string" },
                },
            },
        },
        "build": #{
            "type": "array",
            "maxItems": 10,
            "items": #{
                "type": "object",
                "required": ["id", "title", "why", "acceptance"],
                "properties": #{
                    "id": #{ "type": "string" },
                    "title": #{ "type": "string" },
                    "why": #{ "type": "string" },
                    "acceptance": #{ "type": "string" },
                    "paths": #{ "type": "array", "maxItems": 20, "items": #{ "type": "string" } },
                },
            },
        },
        "do_not_touch": #{ "type": "array", "maxItems": 15, "items": #{ "type": "string" } },
        "success_criteria": #{ "type": "array", "maxItems": 12, "items": #{ "type": "string" } },
    },
};

let work_schema = #{
    "type": "object",
    "required": ["phase", "summary", "changes", "tests_run", "remaining_risks"],
    "properties": #{
        "phase": #{ "type": "string" },
        "summary": #{ "type": "string" },
        "changes": #{
            "type": "array",
            "maxItems": 20,
            "items": #{
                "type": "object",
                "required": ["id", "what", "files", "status"],
                "properties": #{
                    "id": #{ "type": "string" },
                    "what": #{ "type": "string" },
                    "files": #{ "type": "array", "maxItems": 30, "items": #{ "type": "string" } },
                    "status": #{ "type": "string" },
                    "notes": #{ "type": "string" },
                },
            },
        },
        "tests_run": #{ "type": "string" },
        "remaining_risks": #{ "type": "array", "maxItems": 12, "items": #{ "type": "string" } },
    },
};

let verify_schema = #{
    "type": "object",
    "required": ["tests_passed", "health_score", "gaps", "summary", "recommended_next"],
    "properties": #{
        "tests_passed": #{ "type": "boolean" },
        "health_score": #{ "type": "integer" },
        "gaps": #{ "type": "array", "maxItems": 15, "items": #{ "type": "string" } },
        "summary": #{ "type": "string" },
        "recommended_next": #{ "type": "array", "maxItems": 10, "items": #{ "type": "string" } },
        "test_output_excerpt": #{ "type": "string" },
    },
};

// Helpers --------------------------------------------------------------------

fn arr_len(x) {
    if x == () { return 0; }
    if type_of(x) == "array" { return x.len(); }
    0
}

fn as_str(x) {
    if x == () { return ""; }
    if type_of(x) == "string" { return x; }
    "" + x
}

// Shared mission context (kept short; each agent still re-reads the tree) ----

let mission = "";
mission += "You are working in the Edgecraft repo at the workspace root (agentic_trading). ";
mission += "Mission (AGENTS.md): build a FULLY agentic hedge fund on Robinhood MCP — ";
mission += "observe account/history, research markets, form/test hypotheses, place/monitor trades ";
mission += "with deterministic policy/risk gates the model cannot bypass. Backend-first, typed Python, ";
mission += "decimal money, UTC timestamps, idempotent runs, append-only audit, fakes for broker/model, ";
mission += "shadow/dry-run default, live only when explicitly armed. Readable code, no unneeded complexity.\n";
mission += "Elon algorithm (strict order): (1) make requirements less dumb — question every process; ";
mission += "(2) DELETE parts/process/code/docs that do not serve autonomy; (3) simplify/optimize what remains; ";
mission += "(4) accelerate cycle time; (5) automate last. Prefer deletion over abstraction. ";
mission += "Do not invent live broker success. Do not log secrets. Preserve working research/backtest behavior ";
mission += "unless audit proves it is dead or harmful.\n";
mission += "ALWAYS use tools: list_dir, read_file, grep, run tests via shell when allowed. Never answer from memory.\n";

// Optional args: dry_run=true skips mutating phases after plan
let dry_run = false;
if args != () && args.dry_run != () {
    dry_run = args.dry_run == true || args.dry_run == "true";
}

// ============================================================================
// Phase 1: Map
// ============================================================================
phase("Map");
log("Mapping architecture and operational surface");

let map_prompt = mission;
map_prompt += "TASK: Produce a factual map of this repository for agentic autonomous trading.\n";
map_prompt += "Read AGENTS.md, README.md, docs/AUTONOMY.md, docs/HOW_EDGECRAFT_WORKS.md, pyproject.toml, Makefile, ";
map_prompt += "src/edgecraft/*.py (at least module headers and public APIs), cli.py entrypoints, tests layout, examples/, scripts/.\n";
map_prompt += "Identify the true daily autonomy loop (observe→research→decide→gate→execute→reconcile→audit), ";
map_prompt += "CLI entrypoints, package structure, giant modules, dead or orphan code (e.g. pycache without source), ";
map_prompt += "and the highest-risk areas for live trading correctness.\n";
map_prompt += "Output structured fields only. Be concrete with paths.";

let map_r = agent(map_prompt, #{
    label: "map-architecture",
    capability_mode: "read-only",
    agent_type: "explore",
    output_schema: map_schema,
});

let map_json = "{}";
if map_r != () && map_r.success && map_r.output != () {
    map_json = json_encode(map_r.output);
    log("Map complete");
} else {
    log("Map agent failed or empty; continuing with empty map context");
}

// ============================================================================
// Phase 2: Parallel first-principles audit
// ============================================================================
phase("Audit");
log("Running parallel first-principles audits");

let dims = [
    "delete-dead-weight",
    "autonomy-loop-completeness",
    "risk-execution-correctness",
    "code-health-modularity",
    "ops-scheduling-observability",
    "modern-agentic-tooling",
];

let dim_focus = #{
    "delete-dead-weight": "Find code, docs, examples, scripts, frontend, cached artifacts, duplicate models, unused deps, and processes that should be DELETED. Elon step 2. Prefer delete over keep. Evidence from imports/tests/CLI usage.",
    "autonomy-loop-completeness": "Trace observe→research→hypothesis→policy→preflight→permit→execute→reconcile→audit. Gaps that block fully autonomous daily trading (no human in the loop). What is missing vs AGENTS.md.",
    "risk-execution-correctness": "Deterministic gates, idempotency, kill switch, reconciliation, decimal money, market hours, stale data, partial fills, retries. Correctness and fail-closed behavior.",
    "code-health-modularity": "Giant modules (ledger, autonomous_service, codex_runtime, context, cli), unclear ownership, duplication across *models.py, typing, test gaps, complexity that does not buy capability.",
    "ops-scheduling-observability": "Scheduled daily runs (Codex, Makefile, docs/CODEX_SCHEDULED_TASK.md), CLI operator path, structured logs/metrics/health, audit trail usefulness, state/ layout hygiene.",
    "modern-agentic-tooling": "Is the agent surface modern for autonomous trading: tool richness for market/internet data, structured decisions, memory/learning, MCP Robinhood integration, dry-run/shadow/live modes, package/tooling modernity (uv, pyproject, CI).",
};

let audit_jobs = [];
for d in dims {
    let focus = dim_focus[d];
    let p = mission;
    p += "TASK: First-principles AUDIT only (read-only judgment). Dimension: " + d + "\n";
    p += "Focus: " + focus + "\n";
    p += "Architecture map (may be incomplete; re-verify with tools):\n" + map_json + "\n";
    p += "Rules: Question every requirement. Flag process that exists for ceremony not control. ";
    p += "Each finding must have severity in {critical, high, medium, low}, concrete evidence (file:line or command), ";
    p += "action in {DELETE, SIMPLIFY, BUILD, KEEP}, rationale, and paths[]. Max 12 findings. ";
    p += "Empty findings only if you thoroughly searched and found nothing for this dimension.";
    audit_jobs.push(#{
        prompt: p,
        label: "audit:" + d,
        capability_mode: "read-only",
        agent_type: "explore",
        output_schema: audit_schema,
    });
}

let audit_results = parallel(audit_jobs);
let audit_bundle = [];
let ai = 0;
for ar in audit_results {
    if ar != () && ar.success && ar.output != () {
        audit_bundle.push(ar.output);
    } else {
        log("Audit slot failed: " + dims[ai]);
    }
    ai += 1;
}
let audit_json = json_encode(audit_bundle);
log(audit_bundle.len().to_string() + "/" + dims.len().to_string() + " audit dimensions succeeded");

// ============================================================================
// Phase 3: Synthesize plan (delete first)
// ============================================================================
phase("Plan");
log("Synthesizing delete-first improvement plan");

let plan_prompt = mission;
plan_prompt += "TASK: Synthesize a ranked improvement PLAN for this repo. Order must be DELETE then SIMPLIFY then BUILD.\n";
plan_prompt += "Architecture map:\n" + map_json + "\n";
plan_prompt += "Audit findings JSON:\n" + audit_json + "\n";
plan_prompt += "Requirements:\n";
plan_prompt += "- Collapse duplicate/overlapping findings.\n";
plan_prompt += "- DELETE list: only items safe enough for an implementer to remove this run ";
plan_prompt += "(dead code, orphan artifacts not needed by tests, redundant docs/process, unused modules). ";
plan_prompt += "Do not delete live trading safety gates.\n";
plan_prompt += "- SIMPLIFY list: coalesce modules, reduce ceremony, clarify the single autonomy path, ";
plan_prompt += "without rewriting the world.\n";
plan_prompt += "- BUILD list: only gaps that are truly required for a high-performing agentic autonomous fund ";
plan_prompt += "(tools, loop completeness, tests for critical paths). Cap ambition to what fits one serious PR-sized pass.\n";
plan_prompt += "- do_not_touch: safety-critical surfaces that must not be casually rewritten.\n";
plan_prompt += "- success_criteria: measurable (tests pass, CLI smoke, fewer modules, documented operator path).\n";
plan_prompt += "Be ruthless about deletion. Prefer fewer, high-leverage items over laundry lists.";

let plan_r = agent(plan_prompt, #{
    label: "synthesize-plan",
    capability_mode: "read-only",
    agent_type: "plan",
    output_schema: plan_schema,
});

if plan_r == () || !plan_r.success || plan_r.output == () {
    complete(#{
        summary: "Plan synthesis failed; aborting before mutations",
        map: map_json,
        audits: audit_json,
    });
}

let plan = plan_r.output;
let plan_json = json_encode(plan);
let delete_n = arr_len(plan.delete);
let simplify_n = arr_len(plan.simplify);
let build_n = arr_len(plan.build);
let thesis = as_str(plan.thesis);
if thesis == "" { thesis = "(no thesis field from planner)"; }
log("Plan ready: delete=" + delete_n.to_string()
    + " simplify=" + simplify_n.to_string()
    + " build=" + build_n.to_string());

if dry_run {
    let report = "# First-principles fund audit (dry run)\n\n";
    report += "## Thesis\n" + thesis + "\n\n";
    report += "## Plan JSON\n```json\n" + plan_json + "\n```\n";
    let path = write_scratch_file("audit-plan.md", report);
    complete(#{
        summary: "Dry run: plan only, no mutations",
        path: path,
        plan: plan,
        audits: audit_bundle,
    });
}

// ============================================================================
// Phase 4: Delete
// ============================================================================
phase("Delete");
log("Executing DELETE tranche");

let delete_prompt = mission;
delete_prompt += "TASK: Execute the DELETE tranche of the plan. Remove only planned dead weight. Do not gut safety gates.\n";
delete_prompt += "Plan JSON:\n" + plan_json + "\n";
delete_prompt += "Steps:\n";
delete_prompt += "1. For each plan.delete item, verify with grep/tests that it is unused or purely ceremonial.\n";
delete_prompt += "2. Delete or strip only what is justified. Update imports/tests/docs that reference deleted paths.\n";
delete_prompt += "3. Do NOT delete secrets, live mandates under state/, or user data. Prefer not committing binary caches.\n";
delete_prompt += "4. Run focused tests after changes: prefer `uv run pytest -q` or `make test` if available; fix breakage you caused.\n";
delete_prompt += "5. Do not commit unless changes are clean and tests pass; if you commit, use a small coherent message.\n";
delete_prompt += "6. Report each id with status done|skipped|partial and files touched.\n";
delete_prompt += "If a delete is riskier than the plan claimed, SKIP it and explain in remaining_risks.";

let del_r = agent(delete_prompt, #{
    label: "execute-delete",
    capability_mode: "all",
    agent_type: "general-purpose",
    output_schema: work_schema,
});

let del_json = "{}";
if del_r != () && del_r.success && del_r.output != () {
    del_json = json_encode(del_r.output);
    log("Delete phase: " + as_str(del_r.output.summary));
} else {
    log("Delete phase failed or empty");
}

// ============================================================================
// Phase 5: Simplify
// ============================================================================
phase("Simplify");
log("Executing SIMPLIFY tranche");

let simp_prompt = mission;
simp_prompt += "TASK: Execute the SIMPLIFY tranche. Make the autonomy path clearer and modules more cohesive.\n";
simp_prompt += "Plan JSON:\n" + plan_json + "\n";
simp_prompt += "Delete phase report:\n" + del_json + "\n";
simp_prompt += "Rules:\n";
simp_prompt += "- Simplify without big-bang rewrites. Small functions, explicit interfaces, boring typed Python.\n";
simp_prompt += "- Coalesce duplication only when it reduces real complexity.\n";
simp_prompt += "- Preserve public CLI behavior unless the plan explicitly changes it.\n";
simp_prompt += "- Run tests after meaningful edits; fix breakage.\n";
simp_prompt += "- Prefer readable over clever. No new frameworks unless they remove complexity.\n";
simp_prompt += "Report each simplify id with status and files.";

let simp_r = agent(simp_prompt, #{
    label: "execute-simplify",
    capability_mode: "all",
    agent_type: "general-purpose",
    output_schema: work_schema,
});

let simp_json = "{}";
if simp_r != () && simp_r.success && simp_r.output != () {
    simp_json = json_encode(simp_r.output);
    log("Simplify phase: " + as_str(simp_r.output.summary));
} else {
    log("Simplify phase failed or empty");
}

// ============================================================================
// Phase 6: Build required gaps
// ============================================================================
phase("Build");
log("Executing BUILD tranche for autonomy gaps");

let build_prompt = mission;
build_prompt += "TASK: Execute the BUILD tranche — only required gaps for agentic autonomous trading.\n";
build_prompt += "Plan JSON:\n" + plan_json + "\n";
build_prompt += "Delete report:\n" + del_json + "\n";
build_prompt += "Simplify report:\n" + simp_json + "\n";
build_prompt += "Rules:\n";
build_prompt += "- Implement high-leverage gaps first (loop completeness, tool surface, auditability, dry-run safety).\n";
build_prompt += "- Models propose; typed policy/risk authorize. Keep gates deterministic and light.\n";
build_prompt += "- Every new path should be testable with fakes; add/adjust tests for critical behavior.\n";
build_prompt += "- Use decimal for money; UTC timestamps; idempotent intents before side effects.\n";
build_prompt += "- Do not enable live trading by default. Shadow/dry-run remains default.\n";
build_prompt += "- Run the test suite; leave the repo runnable.\n";
build_prompt += "If a build item is too large, implement a vertical slice and note remaining work.";

let build_r = agent(build_prompt, #{
    label: "execute-build",
    capability_mode: "all",
    agent_type: "general-purpose",
    output_schema: work_schema,
});

let build_json = "{}";
if build_r != () && build_r.success && build_r.output != () {
    build_json = json_encode(build_r.output);
    log("Build phase: " + as_str(build_r.output.summary));
} else {
    log("Build phase failed or empty");
}

// ============================================================================
// Phase 7: Verify
// ============================================================================
phase("Verify");
log("Verifying health of the improved repo");

let verify_prompt = mission;
verify_prompt += "TASK: Independently VERIFY the repo health after the improvement pass.\n";
verify_prompt += "Plan:\n" + plan_json + "\n";
verify_prompt += "Delete report:\n" + del_json + "\n";
verify_prompt += "Simplify report:\n" + simp_json + "\n";
verify_prompt += "Build report:\n" + build_json + "\n";
verify_prompt += "Steps:\n";
verify_prompt += "1. Run the full test suite (`uv run pytest -q` or project Makefile). Capture pass/fail honestly.\n";
verify_prompt += "2. Spot-check CLI help / dry-run entrypoints if cheap.\n";
verify_prompt += "3. Adversarially review whether DELETE/SIMPLIFY/BUILD claims are real (git status/diff, read files).\n";
verify_prompt += "4. Score health_score 0-100 for readiness as a modern agentic autonomous trading system.\n";
verify_prompt += "5. List remaining gaps and recommended_next (max 10).\n";
verify_prompt += "Fail closed: if tests did not pass, tests_passed=false.";

let ver_r = agent(verify_prompt, #{
    label: "verify-health",
    capability_mode: "all",
    agent_type: "general-purpose",
    output_schema: verify_schema,
});

let health = 0;
let tests_ok = false;
let verify_summary = "verification missing";
let gaps = [];
let next_steps = [];
let test_excerpt = "";

if ver_r != () && ver_r.success && ver_r.output != () {
    if ver_r.output.health_score != () { health = ver_r.output.health_score; }
    if ver_r.output.tests_passed != () { tests_ok = ver_r.output.tests_passed == true; }
    if ver_r.output.summary != () { verify_summary = as_str(ver_r.output.summary); }
    if ver_r.output.gaps != () && type_of(ver_r.output.gaps) == "array" { gaps = ver_r.output.gaps; }
    if ver_r.output.recommended_next != () && type_of(ver_r.output.recommended_next) == "array" {
        next_steps = ver_r.output.recommended_next;
    }
    if ver_r.output.test_output_excerpt != () { test_excerpt = as_str(ver_r.output.test_output_excerpt); }
    log("Verify complete: health=" + health.to_string() + " tests_passed=" + tests_ok.to_string());
} else {
    log("Verify agent failed");
}

// Final report artifact
let report = "# First-principles fund audit & improvement\n\n";
report += "## Mission lens\n";
report += "Question requirements → delete process → simplify → accelerate → automate. ";
report += "End state: healthy repo for agentic autonomous trading.\n\n";
report += "## Thesis\n" + thesis + "\n\n";
report += "## Verification\n";
report += "- tests_passed: " + tests_ok.to_string() + "\n";
report += "- health_score: " + health.to_string() + "\n";
report += "- summary: " + verify_summary + "\n\n";
if test_excerpt != "" {
    report += "### Test excerpt\n```\n" + test_excerpt + "\n```\n\n";
}
report += "## Plan (JSON)\n```json\n" + plan_json + "\n```\n\n";
report += "## Delete report\n```json\n" + del_json + "\n```\n\n";
report += "## Simplify report\n```json\n" + simp_json + "\n```\n\n";
report += "## Build report\n```json\n" + build_json + "\n```\n\n";
report += "## Remaining gaps\n";
for g in gaps {
    report += "- " + g + "\n";
}
report += "\n## Recommended next\n";
for n in next_steps {
    report += "- " + n + "\n";
}
report += "\n## Audit dimensions (raw)\n```json\n" + audit_json + "\n```\n";

let report_path = write_scratch_file("first-principles-report.md", report);

complete(#{
    summary: verify_summary,
    path: report_path,
    tests_passed: tests_ok,
    health_score: health,
    thesis: thesis,
    delete_count: delete_n,
    simplify_count: simplify_n,
    build_count: build_n,
    gaps: gaps,
    recommended_next: next_steps,
});
