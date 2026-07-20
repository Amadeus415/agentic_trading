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


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")
