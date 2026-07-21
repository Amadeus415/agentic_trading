from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from edgecraft import __version__
from edgecraft.evaluation import evaluation_report
from edgecraft.execution_models import PortfolioSnapshot
from edgecraft.ledger import AuditLedger
from edgecraft.portfolio import analyze_portfolio

LOGGER_NAME = "edgecraft.autonomy"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict):
            payload.update(event_data)
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def configure_logging() -> None:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    level = os.getenv("EDGECRAFT_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level, logging.INFO))
    logger.propagate = False


def log_event(event: str, **fields: Any) -> None:
    configure_logging()
    logging.getLogger(LOGGER_NAME).info(event, extra={"event_data": fields})


def autonomy_health(ledger: AuditLedger) -> dict[str, Any]:
    snapshot = ledger.operational_snapshot()
    last_success = snapshot["last_success_at"]
    last_success_age_seconds = None
    if last_success:
        observed = datetime.fromisoformat(last_success)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        last_success_age_seconds = max(
            0, int((datetime.now(UTC) - observed.astimezone(UTC)).total_seconds())
        )

    reasons = []
    if snapshot["trading_halted"]:
        reasons.append("trading kill switch is active")
    if snapshot["unresolved_order_count"]:
        reasons.append("one or more placed orders are unresolved")
    if snapshot["failed_runs_24h"]:
        reasons.append("one or more autonomous runs failed in the last 24 hours")
    status = "halted" if snapshot["trading_halted"] else "degraded" if reasons else "ready"
    return {
        "status": status,
        "version": __version__,
        "checked_at": datetime.now(UTC).isoformat(),
        "reasons": reasons,
        "last_success_at": last_success,
        "last_success_age_seconds": last_success_age_seconds,
        "snapshot": snapshot,
    }


def prometheus_metrics(ledger: AuditLedger) -> str:
    snapshot = ledger.operational_snapshot()
    lines = [
        "# HELP edgecraft_build_info Static Edgecraft build information.",
        "# TYPE edgecraft_build_info gauge",
        f'edgecraft_build_info{{version="{__version__}"}} 1',
        "# HELP edgecraft_trading_halted Whether the global trading kill switch is active.",
        "# TYPE edgecraft_trading_halted gauge",
        f"edgecraft_trading_halted {int(snapshot['trading_halted'])}",
        "# HELP edgecraft_unresolved_orders Current unresolved placed-order count.",
        "# TYPE edgecraft_unresolved_orders gauge",
        f"edgecraft_unresolved_orders {snapshot['unresolved_order_count']}",
        "# HELP edgecraft_failed_runs_24h Failed autonomous runs in the last 24 hours.",
        "# TYPE edgecraft_failed_runs_24h gauge",
        f"edgecraft_failed_runs_24h {snapshot['failed_runs_24h']}",
        "# HELP edgecraft_runs_total Autonomous runs by current status.",
        "# TYPE edgecraft_runs_total gauge",
    ]
    for status, count in sorted(snapshot["runs_by_status"].items()):
        lines.append(f'edgecraft_runs_total{{status="{_label(status)}"}} {count}')
    lines.extend(
        [
            "# HELP edgecraft_proposals_total Trade proposals by approval result.",
            "# TYPE edgecraft_proposals_total gauge",
        ]
    )
    for approval, count in sorted(snapshot["proposals_by_approval"].items()):
        lines.append(f'edgecraft_proposals_total{{approval="{_label(approval)}"}} {count}')
    lines.extend(
        [
            "# HELP edgecraft_order_events_total Recorded broker order events by type.",
            "# TYPE edgecraft_order_events_total gauge",
        ]
    )
    for event_type, count in sorted(snapshot["order_events_by_type"].items()):
        lines.append(f'edgecraft_order_events_total{{event_type="{_label(event_type)}"}} {count}')
    lines.extend(
        [
            "# HELP edgecraft_permits_total Execution permits by state.",
            "# TYPE edgecraft_permits_total gauge",
        ]
    )
    for status, count in sorted(snapshot["permits_by_status"].items()):
        lines.append(f'edgecraft_permits_total{{status="{_label(status)}"}} {count}')
    return "\n".join(lines) + "\n"


def control_plane_snapshot(ledger: AuditLedger) -> dict[str, Any]:
    """Build the privacy-safe operator view from the append-only ledger."""
    health = autonomy_health(ledger)
    feed = ledger.observability_feed(limit=200, include_decision_packets=False)
    feed["decision_packets"] = ledger.portfolio_snapshot_feed(limit=500)
    runs = ledger.list_runs(limit=100)
    mandates = [
        {
            "mandate_id": item.mandate_id,
            "mode": item.mode,
            "enabled": item.enabled,
            "benchmark": item.benchmark,
            "cycle_frequency": item.cycle_frequency,
            "cycle_budget": float(item.cycle_budget),
            "weekly_budget": float(item.weekly_budget) if item.weekly_budget is not None else None,
            "daily_budget": float(item.daily_budget) if item.daily_budget is not None else None,
            "universe": item.universe,
            "risk_level": item.risk_level,
        }
        for item in ledger.list_mandates()
    ]
    runs_by_id = {item["run_id"]: item for item in runs}
    trades = _trade_summaries(feed, runs_by_id)
    proposals = [
        {
            "proposal_id": item["proposal_id"],
            "mandate_id": item["mandate_id"],
            "run_id": item["run_id"],
            "created_at": item["created_at"],
            "mode": item["mode"],
            "approved_for_review": bool(item["approved_for_review"]),
            "strategy": item["payload"].get("strategy"),
            "order_count": len(item["payload"].get("orders", [])),
            "gross_notional": item["payload"].get("risk", {}).get("gross_notional"),
            "violations": item["payload"].get("risk", {}).get("violations", []),
        }
        for item in feed["proposals"]
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "audit_ledger",
        "has_history": bool(runs or trades),
        "health": health,
        "mandates": mandates,
        "portfolio": _portfolio_view(feed, trades),
        "performance": _performance_views(ledger, mandates),
        "runs": runs,
        "trades": trades,
        "events": feed["runtime_events"],
        "proposals": proposals,
    }


def _trade_summaries(
    feed: dict[str, list[dict[str, Any]]],
    runs_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    events_by_order: dict[str, list[dict[str, Any]]] = {}
    for event in feed["order_events"]:
        order_key = event["payload"].get("order_key")
        if order_key:
            events_by_order.setdefault(str(order_key), []).append(event)
    summaries = []
    for proposal in feed["proposals"]:
        run = runs_by_id.get(proposal["run_id"], {})
        for order in proposal["payload"].get("orders", []):
            order_key = str(order.get("order_key", ""))
            events = sorted(
                events_by_order.get(order_key, []),
                key=lambda item: (item["occurred_at"], item["id"]),
            )
            last = events[-1] if events else None
            filled = next(
                (
                    item
                    for item in reversed(events)
                    if item["event_type"] in {"filled", "partially_filled"}
                ),
                None,
            )
            placed = next(
                (item for item in events if item["event_type"] == "placed"),
                None,
            )
            status = (
                last["event_type"]
                if last
                else ("shadow" if proposal["mode"] == "shadow" else "proposed")
            )
            fill_payload = filled["payload"] if filled else {}
            run_status = run.get("status")
            summaries.append(
                {
                    "order_key": order_key,
                    "proposal_id": proposal["proposal_id"],
                    "run_id": proposal["run_id"],
                    "mandate_id": proposal["mandate_id"],
                    "mode": proposal["mode"],
                    "status": status,
                    "run_status": run_status,
                    "created_at": proposal["created_at"],
                    "occurred_at": last["occurred_at"] if last else proposal["created_at"],
                    "symbol": order.get("symbol"),
                    "side": order.get("side"),
                    "notional": order.get("notional"),
                    "filled_notional": fill_payload.get("filled_notional"),
                    "average_fill_price": fill_payload.get("average_fill_price"),
                    "fees": fill_payload.get("fees"),
                    "expected_price": order.get("expected_price"),
                    "approved_for_review": bool(proposal["approved_for_review"]),
                    "broker_event_count": len(events),
                    "broker_order_id_present": any(
                        bool(item["payload"].get("broker_order_id")) for item in events
                    ),
                    "confirmed_execution": bool(
                        placed
                        and filled
                        and filled["event_type"] == "filled"
                        and run_status == "completed"
                    ),
                }
            )
    return sorted(summaries, key=lambda item: item["occurred_at"], reverse=True)


def _portfolio_view(
    feed: dict[str, list[dict[str, Any]]],
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    packets = feed["decision_packets"]
    if not packets:
        observations = [
            item for item in feed["runtime_events"] if item["event_type"] == "observation_completed"
        ]
        if not observations:
            return {"status": "unavailable", "history": [], "positions": []}
        latest_event = max(observations, key=lambda item: item["occurred_at"])
        payload = latest_event["payload"]
        as_of = payload.get("observed_at", latest_event["occurred_at"])
        last_broker_trade = next(
            (item for item in trades if item["broker_event_count"] > 0),
            None,
        )
        stale_after_trade = bool(
            last_broker_trade
            and datetime.fromisoformat(last_broker_trade["occurred_at"])
            > datetime.fromisoformat(as_of)
        )
        history = [
            {
                "as_of": item["payload"].get("observed_at", item["occurred_at"]),
                "portfolio_value": item["payload"].get("portfolio_value"),
                "buying_power": item["payload"].get("buying_power"),
                "invested_value": None,
                "run_id": item["run_id"],
            }
            for item in sorted(observations, key=lambda item: item["occurred_at"])
        ]
        return {
            "status": "stale_after_trade" if stale_after_trade else "summary_only",
            "as_of": as_of,
            "portfolio_value": payload.get("portfolio_value"),
            "buying_power": payload.get("buying_power"),
            "invested_value": None,
            "position_count": len(payload.get("position_symbols", [])),
            "positions": [
                {"symbol": symbol, "detail_available": False}
                for symbol in payload.get("position_symbols", [])
            ],
            "snapshot_age_seconds": max(
                0, int((datetime.now(UTC) - datetime.fromisoformat(as_of)).total_seconds())
            ),
            "stale_after_trade": stale_after_trade,
            "last_broker_trade_at": last_broker_trade["occurred_at"] if last_broker_trade else None,
            "history": history,
            "audit_note": (
                "This historical run retained only a redacted observation summary. "
                "Exact quantities, costs, and post-trade holdings were not persisted."
            ),
        }
    latest = max(packets, key=lambda item: item["recorded_at"])
    account_payload = latest["payload"].get("observation", {}).get("account")
    if not account_payload:
        return {"status": "unavailable", "history": [], "positions": []}
    snapshot = PortfolioSnapshot.model_validate(account_payload)
    analysis = analyze_portfolio(snapshot)
    analysis.pop("account_id", None)
    analysis.pop("nickname", None)
    history_by_time: dict[str, dict[str, Any]] = {}
    for packet in sorted(packets, key=lambda item: item["recorded_at"]):
        account = packet["payload"].get("observation", {}).get("account") or {}
        as_of = account.get("as_of")
        if as_of and account.get("portfolio_value") is not None:
            positions = account.get("positions", [])
            history_by_time[as_of] = {
                "as_of": as_of,
                "portfolio_value": account["portfolio_value"],
                "buying_power": account.get("buying_power"),
                "invested_value": sum(
                    float(item.get("quantity", 0)) * float(item.get("market_price", 0))
                    for item in positions
                ),
                "run_id": packet["run_id"],
            }
    last_broker_trade = next(
        (item for item in trades if item["broker_event_count"] > 0),
        None,
    )
    stale_after_trade = bool(
        last_broker_trade
        and datetime.fromisoformat(last_broker_trade["occurred_at"])
        > datetime.fromisoformat(snapshot.as_of.isoformat())
    )
    cost_basis = sum(
        item["quantity"] * item["average_cost"]
        for item in analysis["positions"]
        if item["average_cost"] is not None
    )
    unrealized_pnl = sum(
        item["unrealized_pnl"]
        for item in analysis["positions"]
        if item["unrealized_pnl"] is not None
    )
    return {
        "status": "stale_after_trade" if stale_after_trade else "observed",
        "decision_packet_id": latest["packet_id"],
        "snapshot_age_seconds": max(0, int((datetime.now(UTC) - snapshot.as_of).total_seconds())),
        "stale_after_trade": stale_after_trade,
        "last_broker_trade_at": last_broker_trade["occurred_at"] if last_broker_trade else None,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_return_on_cost": unrealized_pnl / cost_basis if cost_basis else None,
        "history": list(history_by_time.values()),
        **analysis,
    }


def _performance_views(
    ledger: AuditLedger,
    mandates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    views = []
    for mandate in mandates:
        mandate_id = mandate["mandate_id"]
        observations = ledger.evaluation_observations(mandate_id)
        state = ledger.evaluation_state(mandate_id)
        report = evaluation_report(state, observations)
        views.append(
            {
                "mandate_id": mandate_id,
                "benchmark": mandate["benchmark"],
                "report": report,
                "series": [
                    {
                        "observed_at": item.observed_at.isoformat(),
                        "agent": float(item.post_trade_values["agent"]),
                        "benchmark": float(item.post_trade_values["benchmark"]),
                        "strategic": float(item.post_trade_values["strategic"]),
                        "contribution": float(item.contribution),
                        "action": item.agent_action,
                    }
                    for item in observations
                ],
                "execution_quality": ledger.execution_quality(mandate_id),
            }
        )
    return views


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")
