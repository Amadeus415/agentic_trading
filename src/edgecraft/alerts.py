"""Operational health alerts with an optional Slack-compatible webhook sink."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from edgecraft.paper_fund import PaperFundLedger


def build_alerts(
    ledger: PaperFundLedger,
    fund_id: str,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    verification = ledger.verify(fund_id, raise_on_error=False)
    state = ledger.get_state(fund_id)
    alerts: list[dict[str, Any]] = []
    if not verification.chain_ok:
        alerts.append(
            {"severity": "critical", "kind": "chain_failed", "detail": verification.details}
        )
    if not verification.accounting_ok:
        alerts.append(
            {"severity": "critical", "kind": "accounting_failed", "detail": verification.details}
        )
    if state.drawdown >= 0.30:
        alerts.append({"severity": "critical", "kind": "drawdown_30", "value": str(state.drawdown)})
    elif state.drawdown >= 0.15:
        alerts.append({"severity": "warning", "kind": "drawdown_15", "value": str(state.drawdown)})
    cutoff = now - timedelta(hours=24)
    for event in ledger.list_events(fund_id):
        if event.occurred_at < cutoff:
            continue
        if event.event_type == "cycle_rejected":
            alerts.append(
                {
                    "severity": "warning",
                    "kind": "cycle_rejected",
                    "cycle_key": event.payload.get("cycle_key"),
                    "detail": event.payload.get("reason"),
                }
            )
        elif event.event_type == "alert_mark_fetch_failed":
            alerts.append(
                {
                    "severity": "warning",
                    "kind": "mark_fetch_failed",
                    "instrument_id": event.payload.get("instrument_id"),
                    "detail": event.payload.get("detail"),
                }
            )
    return alerts


def send_webhook(url: str, alerts: list[dict[str, Any]]) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("alert webhook must use HTTPS")
    text = "Edgecraft alerts:\n" + "\n".join(
        f"[{item['severity']}] {item['kind']}: {item.get('detail', item.get('value', ''))}"
        for item in alerts
    )
    request = urllib.request.Request(
        url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Edgecraft-paper-fund/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15):  # noqa: S310
        return
