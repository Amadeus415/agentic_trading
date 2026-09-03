from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from edgecraft.alerts import build_alerts
from edgecraft.paper_fund import FundMandate, PaperFundLedger


def test_mark_fetch_failures_surface_as_alerts(tmp_path: Path) -> None:
    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize("fund", FundMandate())
        ledger.record_operational_event(
            "fund",
            "alert_mark_fetch_failed",
            {"instrument_id": "AAPL", "detail": "timeout"},
            occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
        alerts = build_alerts(ledger, "fund", now=datetime(2026, 9, 1, 1, tzinfo=UTC))
    assert alerts[0]["kind"] == "mark_fetch_failed"
    assert alerts[0]["instrument_id"] == "AAPL"
