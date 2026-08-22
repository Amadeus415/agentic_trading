from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from edgecraft import __version__
from edgecraft.analytics import market_diagnostics, portfolio_market_risk
from edgecraft.autonomous_service import AutonomousService, StaticObservationRuntime
from edgecraft.autonomy import policy_digest
from edgecraft.autonomy_models import AgentCyclePayload, Mandate
from edgecraft.codex_runtime import PROMPT_VERSION, CodexRuntime, CodexRuntimeConfig
from edgecraft.context import browserbase_api_key, load_context_service
from edgecraft.data import MarketDataProvider, synthetic_market_data
from edgecraft.evaluation import evaluation_report
from edgecraft.execution_models import PortfolioSnapshot, RiskPolicy
from edgecraft.growth import growth_snapshot
from edgecraft.intelligence import YahooMarketIntelligenceCollector
from edgecraft.ledger import AuditLedger
from edgecraft.models import BacktestRequest, CostModel
from edgecraft.observability import autonomy_health, log_event, prometheus_metrics
from edgecraft.paper_fund import (
    CycleRuntimeMetadata,
    FundDecision,
    FundMandate,
    FundQuote,
    PaperFundLedger,
    PaperFundValidationError,
    mandate_digest,
    request_digest,
)
from edgecraft.portfolio import analyze_portfolio
from edgecraft.promotion import build_research_evidence
from edgecraft.research import run_research
from edgecraft.strategies import STRATEGY_SCHEMAS
from edgecraft.walkforward import walk_forward_validate

DEFAULT_LEDGER = "state/edgecraft-paper.db"
DEFAULT_FUND_LEDGER = "state/edgecraft-fund.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edgecraft",
        description="Research, validate, and risk-gate bounded Robinhood agentic trading.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    _add_research_commands(commands)
    _add_fund_commands(commands)
    _add_operation_commands(commands)
    return parser


def _add_fund_commands(commands: Any) -> None:
    validate = commands.add_parser(
        "fund-validate", help="Validate the persistent paper-fund mandate."
    )
    validate.add_argument("--config", required=True, type=Path)

    initialize = commands.add_parser("fund-init", help="Capitalize the paper fund exactly once.")
    initialize.add_argument("--config", required=True, type=Path)
    initialize.add_argument("--ledger", default=DEFAULT_FUND_LEDGER)

    context = commands.add_parser(
        "fund-context", help="Print the authoritative state and decision contract for Codex."
    )
    context.add_argument("--config", required=True, type=Path)
    context.add_argument("--ledger", default=DEFAULT_FUND_LEDGER)

    run = commands.add_parser(
        "fund-run", help="Apply one researched decision to the simulated paper fund."
    )
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--input", required=True, type=Path)
    run.add_argument("--ledger", default=DEFAULT_FUND_LEDGER)
    run.add_argument(
        "--require-as-of-today",
        action="store_true",
        help="Reject a scheduled input whose UTC as_of date is not today.",
    )
    run.add_argument(
        "--max-decision-age-seconds",
        type=int,
        help="Reject a scheduled decision older than this many seconds.",
    )
    run.add_argument(
        "--require-cycle-key",
        help="Require this exact cycle key for a scheduled run.",
    )

    status = commands.add_parser("fund-status", help="Show the current paper-fund book.")
    status.add_argument("--config", required=True, type=Path)
    status.add_argument("--ledger", default=DEFAULT_FUND_LEDGER)

    performance = commands.add_parser(
        "fund-performance", help="Report bankroll return and the immutable NAV history."
    )
    performance.add_argument("--config", required=True, type=Path)
    performance.add_argument("--ledger", default=DEFAULT_FUND_LEDGER)

    events = commands.add_parser("fund-events", help="List append-only paper-fund events.")
    events.add_argument("--config", required=True, type=Path)
    events.add_argument("--ledger", default=DEFAULT_FUND_LEDGER)
    events.add_argument("--limit", type=int, default=20)

    cycle_detail = commands.add_parser(
        "fund-cycle",
        help="Show the full immutable decision/quotes/fills/audit packet for one cycle.",
    )
    cycle_detail.add_argument("--config", required=True, type=Path)
    cycle_detail.add_argument("--ledger", default=DEFAULT_FUND_LEDGER)
    cycle_detail.add_argument("--cycle-key", required=True)

    audit = commands.add_parser(
        "fund-audit",
        help="Join decision, risk, quotes, fills, events, and verification for one cycle.",
    )
    audit.add_argument("--config", required=True, type=Path)
    audit.add_argument("--ledger", default=DEFAULT_FUND_LEDGER)
    audit.add_argument("--cycle-key", required=True)

    verify = commands.add_parser(
        "fund-verify", help="Verify the paper-fund hash chain and accounting replay."
    )
    verify.add_argument("--config", required=True, type=Path)
    verify.add_argument("--ledger", default=DEFAULT_FUND_LEDGER)


def _add_research_commands(commands: Any) -> None:
    health = commands.add_parser("health", help="Check local tooling and Robinhood MCP readiness.")
    health.add_argument(
        "--real-data-symbol",
        help="Also download and validate one year of market data for this symbol.",
    )
    health.add_argument("--ledger", default=DEFAULT_LEDGER)

    commands.add_parser("strategies", help="Print the machine-readable strategy catalog.")
    context = commands.add_parser(
        "context", help="Collect an auditable Browserbase, SEC, and Bluesky context packet."
    )
    context.add_argument("--config", required=True, type=Path)
    context.add_argument("--symbols", required=True, help="Comma-separated equity symbols.")
    context.add_argument("--output", type=Path)

    intelligence = commands.add_parser(
        "intelligence",
        help="Build a point-in-time cross-sectional market and regime snapshot.",
    )
    intelligence.add_argument("--mandate", required=True, type=Path)
    intelligence.add_argument("--output", type=Path)

    market = commands.add_parser(
        "market",
        help="Compute comparable price, trend, volatility, beta, and correlation diagnostics.",
    )
    market.add_argument("--symbols", required=True, help="Comma-separated equity symbols.")
    market.add_argument("--benchmark", default="SPY")
    market.add_argument("--start", default=str(date.today() - timedelta(days=800)))
    market.add_argument("--end", default=str(date.today() + timedelta(days=1)))
    market.add_argument("--output", type=Path)

    backtest = commands.add_parser("backtest", help="Run an experiment matrix.")
    backtest.add_argument("--config", required=True, type=Path)
    backtest.add_argument("--data-source", choices=["market", "synthetic"], default="market")
    backtest.add_argument(
        "--cost-multiplier",
        type=float,
        default=1.0,
        help="Multiply commission, spread, and slippage for implementation stress testing.",
    )
    backtest.add_argument("--output", type=Path)

    walk = commands.add_parser(
        "walk-forward", help="Select on rolling train windows and score untouched test windows."
    )
    walk.add_argument("--config", required=True, type=Path)
    walk.add_argument("--data-source", choices=["market", "synthetic"], default="market")
    walk.add_argument("--train-sessions", type=int, default=504)
    walk.add_argument("--test-sessions", type=int, default=126)
    walk.add_argument("--step-sessions", type=int)
    walk.add_argument("--benchmark", default="plain_dca")
    walk.add_argument("--output", type=Path)

    portfolio = commands.add_parser(
        "portfolio", help="Analyze a canonical Robinhood portfolio snapshot."
    )
    portfolio.add_argument("--snapshot", required=True, type=Path)
    portfolio.add_argument("--output", type=Path)

    portfolio_risk = commands.add_parser(
        "portfolio-risk", help="Estimate historical market risk for current position weights."
    )
    portfolio_risk.add_argument("--snapshot", required=True, type=Path)
    portfolio_risk.add_argument("--benchmark", default="SPY")
    portfolio_risk.add_argument("--start", default=str(date.today() - timedelta(days=800)))
    portfolio_risk.add_argument("--end", default=str(date.today() + timedelta(days=1)))
    portfolio_risk.add_argument("--output", type=Path)

    evidence = commands.add_parser(
        "evidence", help="Derive immutable live-promotion evidence from research artifacts."
    )
    evidence.add_argument("--backtest", required=True, type=Path)
    evidence.add_argument("--walk-forward", required=True, type=Path)
    evidence.add_argument("--cost-stress", required=True, type=Path)
    evidence.add_argument("--strategy", required=True)
    evidence.add_argument("--benchmark", default="plain_dca")
    evidence.add_argument("--output", type=Path)


def _add_operation_commands(commands: Any) -> None:
    ledger = commands.add_parser("ledger", help="Show audit-ledger status.")
    ledger.add_argument("--path", default=DEFAULT_LEDGER)

    mandate_validate = commands.add_parser(
        "mandate-validate", help="Validate and normalize an autonomous mandate."
    )
    mandate_validate.add_argument("--config", required=True, type=Path)

    mandate_register = commands.add_parser(
        "mandate-register", help="Persist a validated autonomous mandate."
    )
    mandate_register.add_argument("--config", required=True, type=Path)
    mandate_register.add_argument("--ledger", default=DEFAULT_LEDGER)

    mandates = commands.add_parser("mandates", help="List persisted autonomous mandates.")
    mandates.add_argument("--ledger", default=DEFAULT_LEDGER)

    cycle = commands.add_parser(
        "cycle", help="Run one idempotent autonomous portfolio-management cycle."
    )
    cycle.add_argument("--mandate", required=True, type=Path)
    cycle.add_argument("--ledger", default=DEFAULT_LEDGER)
    cycle.add_argument(
        "--observation",
        type=Path,
        help="Use a captured AgentCyclePayload instead of invoking Codex (shadow only).",
    )
    cycle.add_argument(
        "--force",
        action="store_true",
        help="Ignore schedule timing; never bypass budget, policy, risk, or permits.",
    )
    cycle.add_argument(
        "--paper-only",
        action="store_true",
        help="Reject any mandate or policy capable of live broker mutation.",
    )
    cycle.add_argument(
        "--retry-side-effect-free",
        metavar="REASON",
        help=(
            "Authorize a bounded audited retry after the ledger proves no broker side effect; "
            "never bypasses budget, policy, risk, freshness, or permits."
        ),
    )

    runs = commands.add_parser("runs", help="List recent autonomous runs.")
    runs.add_argument("--ledger", default=DEFAULT_LEDGER)
    runs.add_argument("--limit", type=int, default=20)

    decision = commands.add_parser(
        "decision", help="Show immutable decision packets for one autonomous run."
    )
    decision.add_argument("--ledger", default=DEFAULT_LEDGER)
    decision.add_argument("--run-id", required=True)

    performance = commands.add_parser(
        "performance",
        help="Report the cash-flow-matched agent, benchmark, and strategic shadow books.",
    )
    performance.add_argument("--ledger", default=DEFAULT_LEDGER)
    performance.add_argument("--mandate-id", required=True)

    execution_quality = commands.add_parser(
        "execution-quality",
        help="Report decision-to-fill slippage, fill notional, and broker fees.",
    )
    execution_quality.add_argument("--ledger", default=DEFAULT_LEDGER)
    execution_quality.add_argument("--mandate-id", required=True)

    incident_reconcile = commands.add_parser(
        "incident-reconcile",
        help="Close a failed run after independently verified terminal broker events.",
    )
    incident_reconcile.add_argument("--ledger", default=DEFAULT_LEDGER)
    incident_reconcile.add_argument("--run-id", required=True)
    incident_reconcile.add_argument("--reason", required=True)

    halt = commands.add_parser("halt", help="Activate the global trading kill switch.")
    halt.add_argument("--ledger", default=DEFAULT_LEDGER)
    halt.add_argument("--reason", required=True)

    resume = commands.add_parser("resume", help="Clear the global trading kill switch.")
    resume.add_argument("--ledger", default=DEFAULT_LEDGER)
    resume.add_argument("--reason", required=True)

    metrics = commands.add_parser(
        "metrics", help="Emit autonomous operations metrics without account data."
    )
    metrics.add_argument("--ledger", default=DEFAULT_LEDGER)
    metrics.add_argument("--format", choices=["json", "prometheus"], default="json")

    autonomous_health = commands.add_parser(
        "autonomy-health", help="Report autonomous control-plane readiness."
    )
    autonomous_health.add_argument("--ledger", default=DEFAULT_LEDGER)

    readiness = commands.add_parser(
        "readiness",
        help="Fail-closed operational readiness review for one scheduled mandate.",
    )
    readiness.add_argument("--mandate", required=True, type=Path)
    readiness.add_argument("--ledger", default=DEFAULT_LEDGER)
    readiness.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit nonzero when any deterministic readiness check fails.",
    )


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = dispatch(args)
        output = getattr(args, "output", None)
        _emit(payload, output)
        if _should_exit_nonzero(args.command, payload):
            raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": type(exc).__name__, "detail": str(exc)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


def _should_exit_nonzero(command: str, payload: Any) -> bool:
    """Hard-fail schedule gates when health/cycle payloads report not ok.

    Successful cycle outcomes (not_due, held, risk_rejected, shadow_complete,
    completed, in_progress) carry top-level ok=true and exit zero. Only explicit
    ok=false (e.g. unresolved_orders, failed replay) fails the scheduled wake.
    Readiness continues to use --require-ready / exception exit code 2.
    """
    if command not in {"health", "cycle"}:
        return False
    return isinstance(payload, dict) and payload.get("ok") is False


def dispatch(args: argparse.Namespace) -> Any:
    try:
        handler = COMMAND_HANDLERS[args.command]
    except KeyError as exc:
        raise ValueError(f"unsupported command: {args.command}") from exc
    return handler(args)


def _collect_context(args: argparse.Namespace) -> dict[str, Any]:
    service = load_context_service(Path.cwd(), args.config)
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    return service.collect(symbols).model_dump(mode="json")


def _collect_intelligence(args: argparse.Namespace) -> dict[str, Any]:
    mandate = Mandate.model_validate(_read_json(args.mandate))
    return (
        YahooMarketIntelligenceCollector()
        .collect(mandate.universe, benchmark=mandate.benchmark)
        .model_dump(mode="json")
    )


def _market_diagnostics(args: argparse.Namespace) -> dict[str, Any]:
    symbols = _symbols(args.symbols, args.benchmark)
    data = MarketDataProvider().load(symbols, args.start, args.end)
    return market_diagnostics(data, benchmark=args.benchmark.upper())


def _load_fund_config(path: Path) -> tuple[str, FundMandate]:
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ValueError("fund config must be a JSON object")
    fund_id = str(raw.get("fund_id", "")).strip()
    if not fund_id:
        raise ValueError("fund config requires fund_id")
    mandate = FundMandate.model_validate(raw.get("mandate"))
    return fund_id, mandate


def _ensure_fund_initialized(
    ledger: PaperFundLedger,
    fund_id: str,
    mandate: FundMandate,
) -> bool:
    try:
        existing = ledger.get_mandate(fund_id)
    except PaperFundValidationError as exc:
        if "is not initialized" not in str(exc):
            raise
        ledger.initialize(fund_id, mandate)
        return True
    if existing != mandate:
        raise ValueError(
            "checked-in fund mandate differs from the immutable initialized mandate; "
            "start a new fund ID instead of rewriting history"
        )
    return False


def _fund_validate(args: argparse.Namespace) -> dict[str, Any]:
    fund_id, mandate = _load_fund_config(args.config)
    return {
        "ok": True,
        "paper_only": True,
        "fund_id": fund_id,
        "mandate": mandate.model_dump(mode="json"),
    }


def _fund_init(args: argparse.Namespace) -> dict[str, Any]:
    fund_id, mandate = _load_fund_config(args.config)
    with PaperFundLedger(args.ledger) as ledger:
        initialized = _ensure_fund_initialized(ledger, fund_id, mandate)
        state = ledger.get_state(fund_id)
        verification = ledger.verify(fund_id)
    log_event(
        "fund_init",
        fund_id=fund_id,
        initialized=initialized,
        mandate_digest=mandate_digest(mandate),
        verification_ok=verification.ok,
        edgecraft_version=__version__,
    )
    return {
        "ok": True,
        "paper_only": True,
        "initialized": initialized,
        "state": state.model_dump(mode="json"),
        "verification": verification.model_dump(mode="json"),
    }


def _fund_context(args: argparse.Namespace) -> dict[str, Any]:
    fund_id, mandate = _load_fund_config(args.config)
    with PaperFundLedger(args.ledger) as ledger:
        state = ledger.get_state(fund_id)
        cycles = ledger.list_cycles(fund_id)[-10:]
    initial = mandate.initial_cash
    growth = growth_snapshot(
        initial_nav=initial, current_nav=state.nav, objective=mandate.growth_objective
    )
    return {
        "ok": True,
        "paper_only": True,
        "one_sentence": (
            "Codex proposes a daily portfolio decision; deterministic code applies it "
            "to an append-only $1,000 fake-money ledger."
        ),
        "fund_id": fund_id,
        "mandate": mandate.model_dump(mode="json"),
        "state": state.model_dump(mode="json"),
        "performance": {
            "initial_cash": str(initial),
            "profit_and_loss": str(state.nav - initial),
            "return_on_initial_cash": str((state.nav / initial) - 1),
        },
        "growth_objective": growth.model_dump(mode="json"),
        "recent_cycles": cycles,
        "input_contract": {
            "shape": {
                "decision": "FundDecision",
                "quotes": ["FundQuote"],
                "runtime": {
                    "optional": True,
                    "fields": ["prompt_version", "model", "reasoning_effort"],
                    "note": (
                        "Optional provenance retained in the append-only audit trail. "
                        "edgecraft_version, mandate_digest, and input_sha256 are added "
                        "by fund-run."
                    ),
                },
            },
            "decision_schema": FundDecision.model_json_schema(mode="validation"),
            "quote_schema": FundQuote.model_json_schema(mode="validation"),
            "rules": [
                "Use action=hold with no orders when evidence is weak.",
                "Pursue the growth objective through evidence-backed asymmetric opportunities; "
                "the target never overrides deterministic risk checks.",
                "Use explicit buy, sell, short, or cover sides and positive quantities.",
                "Include fresh quotes for every open position and every ordered instrument.",
                "Cite every order to evidence embedded in the decision.",
                "Use only public market data; never call a broker mutation tool.",
                "Every accepted cycle stores decision, evidence, quotes, risk checks, "
                "fills, fees, mandate digest, and runtime provenance in the hash-chained ledger.",
            ],
        },
    }


def _fund_runtime_from_input(
    raw: dict[str, Any],
    *,
    mandate: FundMandate,
    input_path: Path,
    input_sha256: str,
) -> CycleRuntimeMetadata:
    """Build apply-step provenance from optional input.runtime and process metadata."""
    runtime_raw = raw.get("runtime")
    if runtime_raw is None:
        runtime_raw = {}
    if not isinstance(runtime_raw, dict):
        raise ValueError("fund cycle input runtime must be a JSON object when present")
    return CycleRuntimeMetadata(
        edgecraft_version=__version__,
        mandate_digest=mandate_digest(mandate),
        prompt_version=(
            str(runtime_raw["prompt_version"]) if runtime_raw.get("prompt_version") else None
        ),
        model=str(runtime_raw["model"]) if runtime_raw.get("model") else None,
        reasoning_effort=(
            str(runtime_raw["reasoning_effort"]) if runtime_raw.get("reasoning_effort") else None
        ),
        input_path=str(input_path),
        input_sha256=input_sha256,
        recorded_at=datetime.now(UTC),
    )


def _fund_run(args: argparse.Namespace) -> dict[str, Any]:
    fund_id, mandate = _load_fund_config(args.config)
    input_path = Path(args.input)
    raw_text = input_path.read_text(encoding="utf-8")
    input_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    raw = json.loads(raw_text)
    if not isinstance(raw, dict):
        raise ValueError("fund cycle input must be a JSON object")
    decision = FundDecision.model_validate(raw.get("decision"))
    quotes = [FundQuote.model_validate(item) for item in raw.get("quotes", [])]
    runtime = _fund_runtime_from_input(
        raw,
        mandate=mandate,
        input_path=input_path.resolve(),
        input_sha256=input_sha256,
    )
    if decision.fund_id != fund_id:
        raise ValueError("decision fund_id does not match the checked-in fund config")
    if args.require_as_of_today and decision.as_of.date() != datetime.now(UTC).date():
        raise ValueError(
            f"scheduled decision as_of date {decision.as_of.date()} is not today's UTC date"
        )
    if args.max_decision_age_seconds is not None:
        if args.max_decision_age_seconds < 1:
            raise ValueError("max decision age must be positive")
        age = (datetime.now(UTC) - decision.as_of).total_seconds()
        if age < -60 or age > args.max_decision_age_seconds:
            raise ValueError(
                f"scheduled decision age {int(age)}s is outside the allowed "
                f"window of {args.max_decision_age_seconds}s"
            )
    if args.require_cycle_key and decision.cycle_key != args.require_cycle_key:
        raise ValueError(
            f"scheduled cycle key {decision.cycle_key!r} does not match "
            f"required key {args.require_cycle_key!r}"
        )
    digest = request_digest(decision, quotes)
    log_event(
        "fund_run_started",
        fund_id=fund_id,
        cycle_key=decision.cycle_key,
        decision_id=decision.decision_id,
        action=decision.action.value,
        request_digest=digest,
        input_path=str(input_path.resolve()),
        input_sha256=input_sha256,
        prompt_version=runtime.prompt_version,
        model=runtime.model,
        edgecraft_version=__version__,
    )
    try:
        with PaperFundLedger(args.ledger) as ledger:
            initialized = _ensure_fund_initialized(ledger, fund_id, mandate)
            result = ledger.execute_cycle(decision, quotes, runtime=runtime)
            verification = ledger.verify(fund_id)
    except Exception as exc:
        log_event(
            "fund_run_failed",
            fund_id=fund_id,
            cycle_key=decision.cycle_key,
            decision_id=decision.decision_id,
            request_digest=digest,
            error_type=type(exc).__name__,
            detail=str(exc),
            input_sha256=input_sha256,
        )
        raise
    log_event(
        "fund_run_completed",
        fund_id=fund_id,
        cycle_key=result.cycle_key,
        decision_id=result.decision_id,
        action=result.action.value,
        request_digest=result.request_digest,
        replayed=result.replayed,
        fill_count=len(result.fills),
        settlement_count=len(result.settlements),
        nav=str(result.state.nav),
        cash=str(result.state.cash),
        risk_approved=result.audit.risk.approved if result.audit else None,
        fee_total=str(result.audit.fee_total) if result.audit else None,
        verification_ok=verification.ok,
        event_sequence=result.event_sequence,
        input_sha256=input_sha256,
    )
    return {
        "ok": True,
        "paper_only": True,
        "initialized": initialized,
        "result": result.model_dump(mode="json"),
        "verification": verification.model_dump(mode="json"),
        "audit": {
            "request_digest": result.request_digest,
            "input_sha256": input_sha256,
            "input_path": str(input_path.resolve()),
            "runtime": runtime.model_dump(mode="json"),
            "risk": result.audit.risk.model_dump(mode="json") if result.audit else None,
        },
    }


def _fund_status(args: argparse.Namespace) -> dict[str, Any]:
    fund_id, mandate = _load_fund_config(args.config)
    with PaperFundLedger(args.ledger) as ledger:
        state = ledger.get_state(fund_id)
        cycles = ledger.list_cycles(fund_id)
        verification = ledger.verify(fund_id)
    return {
        "ok": True,
        "paper_only": True,
        "fund_id": fund_id,
        "state": state.model_dump(mode="json"),
        "performance": {
            "initial_cash": str(mandate.initial_cash),
            "profit_and_loss": str(state.nav - mandate.initial_cash),
            "return_on_initial_cash": str((state.nav / mandate.initial_cash) - 1),
        },
        "growth_objective": growth_snapshot(
            initial_nav=mandate.initial_cash,
            current_nav=state.nav,
            objective=mandate.growth_objective,
        ).model_dump(mode="json"),
        "cycle_count": len(cycles),
        "verification": verification.model_dump(mode="json"),
    }


def _fund_performance(args: argparse.Namespace) -> dict[str, Any]:
    fund_id, mandate = _load_fund_config(args.config)
    with PaperFundLedger(args.ledger) as ledger:
        state = ledger.get_state(fund_id)
        history = ledger.state_history(fund_id)
    initial = mandate.initial_cash
    navs = [initial, *(Decimal(item["nav"]) for item in history)]
    cycle_returns = [
        (current / previous) - 1
        for previous, current in zip(navs, navs[1:], strict=False)
        if previous != 0
    ]
    return {
        "ok": True,
        "paper_only": True,
        "fund_id": fund_id,
        "status": "measuring" if len(history) < 20 else "active",
        "initial_cash": str(initial),
        "current_nav": str(state.nav),
        "profit_and_loss": str(state.nav - initial),
        "total_return": str((state.nav / initial) - 1),
        "growth_objective": growth_snapshot(
            initial_nav=initial,
            current_nav=state.nav,
            objective=mandate.growth_objective,
        ).model_dump(mode="json"),
        "max_drawdown": str(max((Decimal(item["drawdown"]) for item in history), default=0)),
        "positive_cycle_count": sum(item > 0 for item in cycle_returns),
        "negative_cycle_count": sum(item < 0 for item in cycle_returns),
        "hold_count": sum(item["action"] == "hold" for item in history),
        "trade_count": sum(item["action"] == "trade" for item in history),
        "simulated_fill_count": sum(item["fill_count"] for item in history),
        "history": history,
        "interpretation": (
            "Raw bankroll performance only; use a longer frozen history and a market "
            "benchmark before drawing conclusions about skill."
        ),
    }


def _fund_events(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.limit < 1:
        raise ValueError("limit must be positive")
    fund_id, _mandate = _load_fund_config(args.config)
    with PaperFundLedger(args.ledger) as ledger:
        events = ledger.list_events(fund_id)[-args.limit :]
    return [event.model_dump(mode="json") for event in events]


def _fund_cycle(args: argparse.Namespace) -> dict[str, Any]:
    fund_id, _mandate = _load_fund_config(args.config)
    with PaperFundLedger(args.ledger) as ledger:
        cycle = ledger.get_cycle(fund_id, args.cycle_key)
    log_event(
        "fund_cycle_retrieved",
        fund_id=fund_id,
        cycle_key=args.cycle_key,
        request_digest=cycle["request_digest"],
    )
    return {"ok": True, "paper_only": True, "cycle": cycle}


def _fund_audit(args: argparse.Namespace) -> dict[str, Any]:
    fund_id, _mandate = _load_fund_config(args.config)
    with PaperFundLedger(args.ledger) as ledger:
        audit = ledger.cycle_audit(fund_id, args.cycle_key)
    log_event(
        "fund_audit_retrieved",
        fund_id=fund_id,
        cycle_key=args.cycle_key,
        audit_gaps=audit.get("audit_gaps", []),
        ledger_ok=audit.get("reconciliation", {}).get("ledger_ok"),
    )
    return {"ok": True, "paper_only": True, **audit}


def _fund_verify(args: argparse.Namespace) -> dict[str, Any]:
    fund_id, _mandate = _load_fund_config(args.config)
    with PaperFundLedger(args.ledger) as ledger:
        report = ledger.verify(fund_id).model_dump(mode="json")
    log_event(
        "fund_verify",
        fund_id=fund_id,
        ok=report["ok"],
        chain_ok=report["chain_ok"],
        accounting_ok=report["accounting_ok"],
        event_count=report["event_count"],
        cycle_count=report["cycle_count"],
    )
    return report


def _register_mandate(args: argparse.Namespace) -> dict[str, Any]:
    mandate = Mandate.model_validate(_read_json(args.config))
    ledger = AuditLedger(args.ledger)
    ledger.upsert_mandate(mandate)
    return {
        "ok": True,
        "mandate_id": mandate.mandate_id,
        "mode": mandate.mode,
        "ledger": ledger.status(),
    }


def _decision_packets(args: argparse.Namespace) -> list[dict[str, Any]]:
    packets = AuditLedger(args.ledger).decision_packets_for_run(args.run_id)
    if not packets:
        raise ValueError(f"no decision packet found for run_id: {args.run_id}")
    return packets


def _performance(args: argparse.Namespace) -> dict[str, Any]:
    ledger = AuditLedger(args.ledger)
    return evaluation_report(
        ledger.evaluation_state(args.mandate_id),
        ledger.evaluation_observations(args.mandate_id),
    )


def _metrics(args: argparse.Namespace) -> dict[str, Any] | str:
    ledger = AuditLedger(args.ledger)
    return ledger.operational_snapshot() if args.format == "json" else prometheus_metrics(ledger)


def _readiness(args: argparse.Namespace) -> dict[str, Any]:
    result = operational_readiness(Path.cwd(), args.mandate, args.ledger)
    if args.require_ready and not result["ok"]:
        raise RuntimeError("; ".join(result["reasons"]))
    return result


def _toggle_halt(args: argparse.Namespace) -> dict[str, Any]:
    ledger = AuditLedger(args.ledger)
    ledger.set_trading_halt(args.command == "halt", reason=args.reason)
    return {
        "ok": True,
        "trading_halted": ledger.trading_halted(),
        "reason": args.reason,
    }


def _run_cycle(args: argparse.Namespace) -> dict[str, Any]:
    mandate = Mandate.model_validate(_read_json(args.mandate))
    if getattr(args, "paper_only", False):
        if mandate.mode != "shadow":
            raise ValueError("paper-only cycles require a shadow mandate")
        policy = RiskPolicy.model_validate(_read_json(Path(mandate.policy_path)))
        if policy.trading_enabled:
            raise ValueError("paper-only cycles require trading_enabled=false")
    elif mandate.mode != "shadow":
        raise ValueError(
            "live execution is disabled in Edgecraft 0.7; use the $1,000 paper-fund commands"
        )
    ledger = AuditLedger(args.ledger)
    if args.observation:
        if mandate.mode != "shadow":
            raise ValueError("captured observations are restricted to shadow mandates")
        runtime = StaticObservationRuntime(
            AgentCyclePayload.model_validate(_read_json(args.observation))
        )
        intelligence_collector = None
    else:
        runtime = CodexRuntime(CodexRuntimeConfig(repository=Path.cwd()))
        intelligence_collector = YahooMarketIntelligenceCollector()
    context_service = (
        load_context_service(Path.cwd(), mandate.external_context_path)
        if mandate.external_context_path
        else None
    )
    return AutonomousService(
        Path.cwd(),
        ledger,
        runtime,
        context_collector=context_service,
        context_policy=context_service.policy if context_service else None,
        market_intelligence_collector=intelligence_collector,
    ).run_cycle(
        mandate,
        force=args.force,
        retry_side_effect_free_reason=args.retry_side_effect_free,
    )


def _backtest(args: argparse.Namespace) -> dict[str, Any]:
    request = BacktestRequest.model_validate(_read_json(args.config))
    multiplier = float(getattr(args, "cost_multiplier", 1.0))
    if multiplier <= 0:
        raise ValueError("cost_multiplier must be positive")
    if multiplier != 1:
        request = request.model_copy(
            update={
                "costs": CostModel(
                    commission_per_order=request.costs.commission_per_order * multiplier,
                    slippage_bps=request.costs.slippage_bps * multiplier,
                    spread_bps=request.costs.spread_bps * multiplier,
                )
            }
        )
    return run_research(_load_data(request, args.data_source), request)


def _walk_forward(args: argparse.Namespace) -> dict[str, Any]:
    request = BacktestRequest.model_validate(_read_json(args.config))
    return walk_forward_validate(
        _load_data(request, args.data_source),
        request,
        train_sessions=args.train_sessions,
        test_sessions=args.test_sessions,
        step_sessions=args.step_sessions,
        benchmark=args.benchmark,
    )


def _portfolio_risk(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = PortfolioSnapshot.model_validate(_read_json(args.snapshot))
    symbols = _symbols(",".join(position.symbol for position in snapshot.positions), args.benchmark)
    data = MarketDataProvider().load(symbols, args.start, args.end)
    return portfolio_market_risk(snapshot, data, benchmark=args.benchmark.upper())


def _evidence(args: argparse.Namespace) -> dict[str, Any]:
    return build_research_evidence(
        _read_json(args.backtest),
        _read_json(args.walk_forward),
        _read_json(args.cost_stress),
        strategy=args.strategy,
        benchmark=args.benchmark,
    ).model_dump(mode="json")


CommandHandler = Callable[[argparse.Namespace], Any]
COMMAND_HANDLERS: dict[str, CommandHandler] = {
    "health": lambda args: health_check(args.ledger, args.real_data_symbol),
    "strategies": lambda _args: STRATEGY_SCHEMAS,
    "context": _collect_context,
    "intelligence": _collect_intelligence,
    "market": _market_diagnostics,
    "backtest": _backtest,
    "walk-forward": _walk_forward,
    "portfolio": lambda args: analyze_portfolio(
        PortfolioSnapshot.model_validate(_read_json(args.snapshot))
    ),
    "portfolio-risk": _portfolio_risk,
    "evidence": _evidence,
    "fund-validate": _fund_validate,
    "fund-init": _fund_init,
    "fund-context": _fund_context,
    "fund-run": _fund_run,
    "fund-status": _fund_status,
    "fund-performance": _fund_performance,
    "fund-events": _fund_events,
    "fund-cycle": _fund_cycle,
    "fund-audit": _fund_audit,
    "fund-verify": _fund_verify,
    "ledger": lambda args: AuditLedger(args.path).status(),
    "mandate-validate": lambda args: Mandate.model_validate(_read_json(args.config)).model_dump(
        mode="json"
    ),
    "mandate-register": _register_mandate,
    "mandates": lambda args: [
        mandate.model_dump(mode="json") for mandate in AuditLedger(args.ledger).list_mandates()
    ],
    "cycle": _run_cycle,
    "runs": lambda args: AuditLedger(args.ledger).list_runs(limit=args.limit),
    "decision": _decision_packets,
    "performance": _performance,
    "execution-quality": lambda args: AuditLedger(args.ledger).execution_quality(args.mandate_id),
    "incident-reconcile": lambda args: AuditLedger(args.ledger).reconcile_failed_run(
        args.run_id, reason=args.reason
    ),
    "halt": _toggle_halt,
    "resume": _toggle_halt,
    "metrics": _metrics,
    "autonomy-health": lambda args: autonomy_health(AuditLedger(args.ledger)),
    "readiness": _readiness,
}


def health_check(ledger_path: str, real_data_symbol: str | None = None) -> dict[str, Any]:
    codex_path = shutil.which("codex")
    mcp = {
        "configured": False,
        "enabled": False,
        "endpoint": None,
        "detail": "codex executable not found",
    }
    if codex_path:
        result = subprocess.run(
            [codex_path, "mcp", "get", "robinhood-trading"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        text = result.stdout + result.stderr
        mcp = {
            "configured": result.returncode == 0,
            "enabled": "enabled: true" in text,
            "endpoint": (
                "https://agent.robinhood.com/mcp/trading"
                if "https://agent.robinhood.com/mcp/trading" in text
                else None
            ),
            "detail": text.strip(),
        }
    market_data = {"checked": False}
    if real_data_symbol:
        end = date.today() + timedelta(days=1)
        start = end - timedelta(days=500)
        symbol = real_data_symbol.strip().upper()
        data = MarketDataProvider().load([symbol], start.isoformat(), end.isoformat(), refresh=True)
        frame = data[symbol]
        market_data = {
            "checked": True,
            "symbol": symbol,
            "sessions": len(frame),
            "first_session": str(frame.index[0].date()),
            "last_session": str(frame.index[-1].date()),
            "last_close": float(frame["close"].iloc[-1]),
        }
    ledger = AuditLedger(ledger_path).status()
    ready = mcp["configured"] and mcp["enabled"] and mcp["endpoint"] is not None
    if real_data_symbol:
        ready = ready and bool(market_data.get("sessions", 0) >= 60)
    return {
        "ok": ready,
        "version": __version__,
        "checked_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "robinhood_mcp": mcp,
        "market_data": market_data,
        "ledger": ledger,
        "web_context": {
            "provider": "browserbase",
            "configured": bool(browserbase_api_key()),
            "search_endpoint": "https://api.browserbase.com/v1/search",
            "fetch_endpoint": "https://api.browserbase.com/v1/fetch",
        },
        "note": "Health verifies configuration, not current account eligibility; refresh get_accounts.",
    }


def operational_readiness(
    repository: Path,
    mandate_path: Path,
    ledger_path: str | Path,
) -> dict[str, Any]:
    mandate_file = mandate_path if mandate_path.is_absolute() else repository / mandate_path
    mandate = Mandate.model_validate(_read_json(mandate_file))
    policy_file = Path(mandate.policy_path)
    policy_file = policy_file if policy_file.is_absolute() else repository / policy_file
    raw_policy = _read_json(policy_file)
    policy = RiskPolicy.model_validate(raw_policy)
    ledger = AuditLedger(ledger_path)
    reasons = _base_readiness_reasons(repository, mandate, policy, ledger)
    history_id = (
        mandate.promotion_source_mandate_id or mandate.mandate_id
        if mandate.mode == "live"
        else mandate.mandate_id
    )
    shadow_cycles = ledger.successful_shadow_cycle_count(history_id)
    if mandate.mode == "live":
        reasons.extend(
            _live_readiness_reasons(
                repository,
                mandate,
                policy,
                raw_policy,
                shadow_cycles,
            )
        )
    return {
        "ok": not reasons,
        "checked_at": datetime.now(UTC).isoformat(),
        "mandate_id": mandate.mandate_id,
        "mode": mandate.mode,
        "policy_name": policy.policy_name,
        "policy_digest": policy_digest(policy),
        "prompt_version": PROMPT_VERSION,
        "successful_shadow_cycles": shadow_cycles,
        "reasons": reasons,
    }


def _base_readiness_reasons(
    repository: Path,
    mandate: Mandate,
    policy: RiskPolicy,
    ledger: AuditLedger,
) -> list[str]:
    reasons = []
    if not mandate.enabled:
        reasons.append("mandate is disabled")
    if mandate.mode == "live" and not policy.trading_enabled:
        reasons.append("live mandate policy has trading_enabled=false")
    if not set(mandate.universe).issubset(set(policy.allowed_symbols)):
        reasons.append("mandate universe is not a subset of the policy whitelist")
    unresolved = ledger.unresolved_order_keys()
    if ledger.trading_halted() and not unresolved:
        # Halt with unresolved orders is allowed so the next cycle can re-reconcile
        # fills before any new risk approval. Cycle blocks new work until terminal.
        reasons.append("trading kill switch is active")
    # Unresolved orders are not a readiness hard-fail: run_cycle re-reconciles them
    # first and refuses new proposals until every key is terminal.
    if shutil.which("codex") is None:
        reasons.append("codex executable is unavailable")
    if mandate.external_context_path:
        context_path = Path(mandate.external_context_path)
        context_path = context_path if context_path.is_absolute() else repository / context_path
        if not context_path.is_file():
            reasons.append("external context configuration is missing")
    return reasons


def _live_readiness_reasons(
    repository: Path,
    mandate: Mandate,
    policy: RiskPolicy,
    raw_policy: dict[str, Any],
    shadow_cycles: int,
) -> list[str]:
    reasons = []
    if not (repository / ".codex" / "hooks.json").is_file():
        reasons.append("live mandate requires the repository trade-permit hook")
    required_policy_fields = {
        "allowed_market_sessions",
        "max_drawdown_fraction",
        "max_order_adv_fraction",
        "max_rolling_7d_turnover",
        "max_spread_bps",
        "min_shadow_cycles_before_live",
    }
    missing = sorted(required_policy_fields - set(raw_policy))
    if missing:
        reasons.append("live policy must explicitly set production controls: " + ", ".join(missing))
    if shadow_cycles < policy.min_shadow_cycles_before_live:
        reasons.append(
            f"shadow history has {shadow_cycles} successful cycle(s), "
            f"below required {policy.min_shadow_cycles_before_live}"
        )
    return reasons


def _load_data(request: BacktestRequest, source: str):
    if source == "synthetic":
        return synthetic_market_data(
            request.symbols,
            periods=max(1_500, 504 + 126 * 4),
            seed=request.validation.random_seed,
        )
    return MarketDataProvider().load(
        request.symbols, request.start.isoformat(), request.end.isoformat()
    )


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _symbols(value: str, benchmark: str) -> list[str]:
    clean = [symbol.strip().upper() for symbol in value.split(",") if symbol.strip()]
    benchmark = benchmark.strip().upper()
    if benchmark not in clean:
        clean.append(benchmark)
    if not clean:
        raise ValueError("at least one symbol is required")
    return list(dict.fromkeys(clean))


def _emit(payload: Any, output: Path | None) -> None:
    text = (
        payload.rstrip()
        if isinstance(payload, str)
        else json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    )
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "output": str(output.resolve())}))
    else:
        print(text)


if __name__ == "__main__":
    main()
