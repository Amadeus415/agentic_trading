from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from edgecraft import __version__
from edgecraft.analytics import market_diagnostics, portfolio_market_risk
from edgecraft.data import MarketDataProvider, synthetic_market_data
from edgecraft.execution_models import (
    MarketQuote,
    PortfolioSnapshot,
    ResearchEvidence,
    RiskPolicy,
    TargetAllocation,
)
from edgecraft.ledger import AuditLedger
from edgecraft.models import BacktestRequest, CostModel
from edgecraft.orchestration import create_trade_proposal, robinhood_protocol
from edgecraft.portfolio import analyze_portfolio
from edgecraft.promotion import build_research_evidence
from edgecraft.research import run_research
from edgecraft.strategies import STRATEGY_SCHEMAS
from edgecraft.walkforward import walk_forward_validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edgecraft",
        description="Research, validate, and risk-gate bounded Robinhood agentic trading.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    health = commands.add_parser("health", help="Check local tooling and Robinhood MCP readiness.")
    health.add_argument(
        "--real-data-symbol",
        help="Also download and validate one year of market data for this symbol.",
    )
    health.add_argument("--ledger", default="state/edgecraft.db")

    commands.add_parser("strategies", help="Print the machine-readable strategy catalog.")
    commands.add_parser("protocol", help="Print the Robinhood orchestration contract.")

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

    propose = commands.add_parser(
        "propose", help="Create an idempotent, risk-gated shadow or live trade proposal."
    )
    propose.add_argument("--snapshot", required=True, type=Path)
    propose.add_argument("--quotes", required=True, type=Path)
    propose.add_argument("--targets", required=True, type=Path)
    propose.add_argument("--policy", required=True, type=Path)
    propose.add_argument("--strategy", required=True)
    propose.add_argument("--mode", choices=["shadow", "live"], default="shadow")
    propose.add_argument("--research", type=Path)
    propose.add_argument("--ledger", default="state/edgecraft.db")
    propose.add_argument("--output", type=Path)

    record = commands.add_parser(
        "record", help="Record a Robinhood review/order/fill/cancel event in the audit ledger."
    )
    record.add_argument("--ledger", default="state/edgecraft.db")
    record.add_argument("--proposal-id", required=True)
    record.add_argument(
        "--event",
        required=True,
        choices=["reviewed", "placed", "filled", "partially_filled", "rejected", "canceled"],
    )
    record.add_argument("--payload", required=True, type=Path)
    record.add_argument("--idempotency-key")

    ledger = commands.add_parser("ledger", help="Show audit-ledger status.")
    ledger.add_argument("--path", default="state/edgecraft.db")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = dispatch(args)
        output = getattr(args, "output", None)
        _emit(payload, output)
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": type(exc).__name__, "detail": str(exc)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


def dispatch(args: argparse.Namespace) -> dict[str, Any] | list[dict[str, Any]]:
    if args.command == "health":
        return health_check(args.ledger, args.real_data_symbol)
    if args.command == "strategies":
        return STRATEGY_SCHEMAS
    if args.command == "protocol":
        return robinhood_protocol()
    if args.command == "market":
        symbols = _symbols(args.symbols, args.benchmark)
        data = MarketDataProvider().load(symbols, args.start, args.end)
        return market_diagnostics(data, benchmark=args.benchmark.upper())
    if args.command == "ledger":
        return AuditLedger(args.path).status()
    if args.command == "backtest":
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
        data = _load_data(request, args.data_source)
        return run_research(data, request)
    if args.command == "walk-forward":
        request = BacktestRequest.model_validate(_read_json(args.config))
        data = _load_data(request, args.data_source)
        return walk_forward_validate(
            data,
            request,
            train_sessions=args.train_sessions,
            test_sessions=args.test_sessions,
            step_sessions=args.step_sessions,
            benchmark=args.benchmark,
        )
    if args.command == "portfolio":
        return analyze_portfolio(PortfolioSnapshot.model_validate(_read_json(args.snapshot)))
    if args.command == "portfolio-risk":
        snapshot = PortfolioSnapshot.model_validate(_read_json(args.snapshot))
        symbols = [position.symbol for position in snapshot.positions]
        symbols = _symbols(",".join(symbols), args.benchmark)
        data = MarketDataProvider().load(symbols, args.start, args.end)
        return portfolio_market_risk(snapshot, data, benchmark=args.benchmark.upper())
    if args.command == "evidence":
        return build_research_evidence(
            _read_json(args.backtest),
            _read_json(args.walk_forward),
            _read_json(args.cost_stress),
            strategy=args.strategy,
            benchmark=args.benchmark,
        ).model_dump(mode="json")
    if args.command == "propose":
        snapshot = PortfolioSnapshot.model_validate(_read_json(args.snapshot))
        quote_payload = _read_json(args.quotes)
        raw_quotes = (
            quote_payload.get("quotes", []) if isinstance(quote_payload, dict) else quote_payload
        )
        quotes = [MarketQuote.model_validate(item) for item in raw_quotes]
        targets = TargetAllocation.model_validate(_read_json(args.targets))
        policy = RiskPolicy.model_validate(_read_json(args.policy))
        research = (
            ResearchEvidence.model_validate(_read_json(args.research)) if args.research else None
        )
        return create_trade_proposal(
            snapshot,
            quotes,
            targets,
            policy,
            strategy=args.strategy,
            mode=args.mode,
            ledger=AuditLedger(args.ledger),
            research=research,
        ).model_dump(mode="json")
    if args.command == "record":
        payload = _read_json(args.payload)
        ledger = AuditLedger(args.ledger)
        key = ledger.record_event(
            args.proposal_id,
            args.event,
            payload,
            idempotency_key=args.idempotency_key,
        )
        return {"ok": True, "idempotency_key": key, "ledger": ledger.status()}
    raise ValueError(f"unsupported command: {args.command}")


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
        "note": "Health verifies configuration, not current account eligibility; refresh get_accounts.",
    }


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
    text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "output": str(output.resolve())}))
    else:
        print(text)


if __name__ == "__main__":
    main()
