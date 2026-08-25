from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from edgecraft import __version__
from edgecraft.fund_brain import build_fund_brain
from edgecraft.growth import growth_snapshot
from edgecraft.observability import log_event
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

DEFAULT_FUND_LEDGER = "state/edgecraft-aggressive.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edgecraft",
        description="Apply sourced paper-fund decisions to an append-only $1,000 fake-money ledger.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    _add_fund_commands(commands)
    _add_lab_commands(commands)
    return parser


def _fund_parent() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--config", required=True, type=Path)
    parent.add_argument("--ledger", default=DEFAULT_FUND_LEDGER)
    return parent


def _add_fund_commands(commands: Any) -> None:
    fund = _fund_parent()

    validate = commands.add_parser(
        "fund-validate", help="Validate the persistent paper-fund mandate."
    )
    validate.add_argument("--config", required=True, type=Path)

    commands.add_parser("fund-init", parents=[fund], help="Capitalize the paper fund exactly once.")
    commands.add_parser(
        "fund-context",
        parents=[fund],
        help="Print the authoritative state and decision contract for Codex.",
    )

    run = commands.add_parser(
        "fund-run",
        parents=[fund],
        help="Apply one researched decision to the simulated paper fund.",
    )
    run.add_argument("--input", required=True, type=Path)
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
    run.add_argument(
        "--require-brain-journal",
        action="store_true",
        help="Require structured hypotheses for every open or ordered instrument.",
    )

    show = commands.add_parser(
        "fund-show",
        parents=[fund],
        help="Show the current book, brain, and optional history or events.",
    )
    show.add_argument(
        "--history",
        action="store_true",
        help="Include immutable NAV history and bankroll performance.",
    )
    show.add_argument(
        "--events",
        action="store_true",
        help="Include the most recent hash-chained events.",
    )
    show.add_argument("--limit", type=int, default=20, help="Event tail length when --events.")

    cycle_detail = commands.add_parser(
        "fund-cycle",
        parents=[fund],
        help="Show the immutable packet for one cycle.",
    )
    cycle_detail.add_argument("--cycle-key", required=True)
    cycle_detail.add_argument(
        "--audit",
        action="store_true",
        help="Include related events and sidecar completeness gaps (does not replay accounting).",
    )

    commands.add_parser(
        "fund-verify",
        parents=[fund],
        help="Verify the paper-fund hash chain and accounting replay.",
    )


def _add_lab_commands(commands: Any) -> None:
    commands.add_parser(
        "strategies", help="Print the machine-readable research-lab strategy catalog."
    )
    market = commands.add_parser(
        "market",
        help="Compute comparable price, trend, volatility, beta, and correlation diagnostics.",
    )
    market.add_argument("--symbols", required=True, help="Comma-separated equity symbols.")
    market.add_argument("--benchmark", default="SPY")
    market.add_argument("--start", default=str(date.today() - timedelta(days=800)))
    market.add_argument("--end", default=str(date.today() + timedelta(days=1)))
    market.add_argument("--output", type=Path)

    backtest = commands.add_parser("backtest", help="Run a research-lab experiment matrix.")
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


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = dispatch(args)
        output = getattr(args, "output", None)
        _emit(payload, output)
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


def dispatch(args: argparse.Namespace) -> Any:
    try:
        handler = COMMAND_HANDLERS[args.command]
    except KeyError as exc:
        raise ValueError(f"unsupported command: {args.command}") from exc
    return handler(args)


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
        brain = build_fund_brain(ledger, fund_id)
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
        "performance": _pnl_snapshot(initial, state.nav),
        "growth_objective": growth.model_dump(mode="json"),
        "recent_cycles": cycles,
        "brain": brain.model_dump(mode="json"),
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
                "Scheduled decisions require an auditable journal with one current "
                "hypothesis for every open or ordered instrument.",
                "Use the ledger-derived brain as feedback, not causal proof of skill.",
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
            result = ledger.execute_cycle(
                decision,
                quotes,
                runtime=runtime,
                require_brain_journal=args.require_brain_journal,
            )
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


def _fund_show(args: argparse.Namespace) -> dict[str, Any]:
    if args.limit < 1:
        raise ValueError("limit must be positive")
    fund_id, mandate = _load_fund_config(args.config)
    with PaperFundLedger(args.ledger) as ledger:
        state = ledger.get_state(fund_id)
        cycles = ledger.list_cycles(fund_id)
        brain = build_fund_brain(ledger, fund_id)
        payload: dict[str, Any] = {
            "ok": True,
            "paper_only": True,
            "fund_id": fund_id,
            "state": state.model_dump(mode="json"),
            "performance": _pnl_snapshot(mandate.initial_cash, state.nav),
            "growth_objective": growth_snapshot(
                initial_nav=mandate.initial_cash,
                current_nav=state.nav,
                objective=mandate.growth_objective,
            ).model_dump(mode="json"),
            "cycle_count": len(cycles),
            "brain": brain.model_dump(mode="json"),
        }
        if args.history:
            payload["history"] = _performance_history(ledger, fund_id, mandate, state)
        if args.events:
            payload["events"] = [
                event.model_dump(mode="json")
                for event in ledger.list_events(fund_id)[-args.limit :]
            ]
    return payload


def _fund_cycle(args: argparse.Namespace) -> dict[str, Any]:
    fund_id, _mandate = _load_fund_config(args.config)
    with PaperFundLedger(args.ledger) as ledger:
        cycle = ledger.get_cycle(fund_id, args.cycle_key)
        payload: dict[str, Any] = {"ok": True, "paper_only": True, "cycle": cycle}
        if args.audit:
            payload["audit"] = ledger.cycle_audit(fund_id, args.cycle_key)
    log_event(
        "fund_cycle_retrieved",
        fund_id=fund_id,
        cycle_key=args.cycle_key,
        request_digest=cycle["request_digest"],
        audit=bool(args.audit),
    )
    return payload


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


def _pnl_snapshot(initial: Decimal, nav: Decimal) -> dict[str, str]:
    return {
        "initial_cash": str(initial),
        "profit_and_loss": str(nav - initial),
        "return_on_initial_cash": str((nav / initial) - 1),
    }


def _performance_history(
    ledger: PaperFundLedger,
    fund_id: str,
    mandate: FundMandate,
    state: Any,
) -> dict[str, Any]:
    history = ledger.state_history(fund_id)
    initial = mandate.initial_cash
    navs = [initial, *(Decimal(item["nav"]) for item in history)]
    cycle_returns = [
        (current / previous) - 1
        for previous, current in zip(navs, navs[1:], strict=False)
        if previous != 0
    ]
    return {
        "status": "measuring" if len(history) < 20 else "active",
        "initial_cash": str(initial),
        "current_nav": str(state.nav),
        "profit_and_loss": str(state.nav - initial),
        "total_return": str((state.nav / initial) - 1),
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


def _lab_unavailable() -> RuntimeError:
    return RuntimeError(
        "research lab commands require the lab extra; install with "
        "`uv sync --extra lab` or `uv sync --extra dev`"
    )


def _strategies(_args: argparse.Namespace) -> Any:
    try:
        from edgecraft.strategies import STRATEGY_SCHEMAS
    except ImportError as exc:
        raise _lab_unavailable() from exc
    return STRATEGY_SCHEMAS


def _market_diagnostics(args: argparse.Namespace) -> dict[str, Any]:
    try:
        from edgecraft.analytics import market_diagnostics
        from edgecraft.data import MarketDataProvider
    except ImportError as exc:
        raise _lab_unavailable() from exc
    symbols = _symbols(args.symbols, args.benchmark)
    data = MarketDataProvider().load(symbols, args.start, args.end)
    return market_diagnostics(data, benchmark=args.benchmark.strip().upper())


def _backtest(args: argparse.Namespace) -> dict[str, Any]:
    try:
        from edgecraft.models import BacktestRequest
        from edgecraft.research import run_research
    except ImportError as exc:  # pragma: no cover - optional extra
        raise _lab_unavailable() from exc
    request = BacktestRequest.model_validate(_read_json(args.config))
    if args.cost_multiplier != 1.0:
        request = request.model_copy(
            update={"cost_model": _scale_cost_model(request.cost_model, args.cost_multiplier)}
        )
    return run_research(_load_data(request, args.data_source), request)


def _walk_forward(args: argparse.Namespace) -> dict[str, Any]:
    try:
        from edgecraft.models import BacktestRequest
        from edgecraft.walkforward import walk_forward_validate
    except ImportError as exc:
        raise _lab_unavailable() from exc
    request = BacktestRequest.model_validate(_read_json(args.config))
    return walk_forward_validate(
        _load_data(request, args.data_source),
        request,
        train_sessions=args.train_sessions,
        test_sessions=args.test_sessions,
        step_sessions=args.step_sessions,
        benchmark=args.benchmark,
    )


def _scale_cost_model(model: Any, multiplier: float) -> Any:
    from edgecraft.models import CostModel

    return CostModel(
        commission_bps=model.commission_bps * multiplier,
        spread_bps=model.spread_bps * multiplier,
        slippage_bps=model.slippage_bps * multiplier,
    )


def _load_data(request: Any, source: str):
    from edgecraft.data import MarketDataProvider, synthetic_market_data

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


CommandHandler = Callable[[argparse.Namespace], Any]
COMMAND_HANDLERS: dict[str, CommandHandler] = {
    "fund-validate": _fund_validate,
    "fund-init": _fund_init,
    "fund-context": _fund_context,
    "fund-run": _fund_run,
    "fund-show": _fund_show,
    "fund-cycle": _fund_cycle,
    "fund-verify": _fund_verify,
    "strategies": _strategies,
    "market": _market_diagnostics,
    "backtest": _backtest,
    "walk-forward": _walk_forward,
}


if __name__ == "__main__":
    main()
