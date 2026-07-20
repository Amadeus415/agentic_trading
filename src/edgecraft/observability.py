from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from edgecraft import __version__
from edgecraft.ledger import AuditLedger

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
    feed = ledger.observability_feed(limit=200)
    runs = ledger.list_runs(limit=100)
    mandates = [
        {
            "mandate_id": item.mandate_id,
            "mode": item.mode,
            "enabled": item.enabled,
            "benchmark": item.benchmark,
            "weekly_budget": float(item.weekly_budget),
            "universe": item.universe,
            "risk_level": item.risk_level,
        }
        for item in ledger.list_mandates()
    ]
    trades = []
    for event in feed["order_events"]:
        payload = event["payload"]
        trades.append(
            {
                "id": event["id"],
                "proposal_id": event["proposal_id"],
                "run_id": event["run_id"],
                "mandate_id": event["mandate_id"],
                "status": event["event_type"],
                "occurred_at": event["occurred_at"],
                "symbol": payload.get("symbol"),
                "side": payload.get("side"),
                "notional": payload.get("notional", payload.get("filled_notional")),
                "filled_notional": payload.get("filled_notional"),
                "broker_order_id_present": bool(payload.get("broker_order_id")),
            }
        )
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
        "runs": runs,
        "trades": trades,
        "events": feed["runtime_events"],
        "proposals": proposals,
    }


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")
