"""Derived daily NAV reconstruction from code-owned historical marks."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from edgecraft.marketdata import MarketDataRouter
from edgecraft.paper_fund import AssetClass, PaperFundLedger

ZERO = Decimal("0")


def build_daily_nav_backfill(
    ledger: PaperFundLedger,
    fund_id: str,
    router: MarketDataRouter,
) -> dict[str, Any]:
    cycles = ledger.list_full_cycles(fund_id)
    if not cycles:
        return {"schema_version": "edgecraft.daily-nav.v1", "fund_id": fund_id, "days": []}
    start = datetime.fromisoformat(str(cycles[0]["as_of"]).replace("Z", "+00:00")).astimezone(UTC)
    end = datetime.fromisoformat(str(cycles[-1]["as_of"]).replace("Z", "+00:00")).astimezone(UTC)
    instruments: dict[str, AssetClass] = {}
    for cycle in cycles:
        for position in cycle["state"].get("positions", []):
            instruments[str(position["instrument_id"])] = AssetClass(position["asset_class"])
    histories: dict[str, list[tuple[datetime, Decimal]]] = {}
    errors: dict[str, str] = {}
    for instrument, asset in instruments.items():
        try:
            histories[instrument] = router.history(
                instrument,
                asset,
                start=start - timedelta(days=1),
                end=end + timedelta(days=2),
            )
        except Exception as exc:
            histories[instrument] = []
            errors[instrument] = str(exc)
    days: list[dict[str, Any]] = []
    cursor = start.date()
    while cursor <= end.date():
        cutoff = datetime.combine(cursor, time.max, tzinfo=UTC)
        eligible = [
            cycle
            for cycle in cycles
            if datetime.fromisoformat(str(cycle["as_of"]).replace("Z", "+00:00")) <= cutoff
        ]
        if not eligible:
            cursor += timedelta(days=1)
            continue
        state = eligible[-1]["state"]
        nav = Decimal(str(state["cash"]))
        coverage = 0
        positions = state.get("positions", [])
        marks: dict[str, str] = {}
        for position in positions:
            instrument = str(position["instrument_id"])
            observations = [item for item in histories.get(instrument, []) if item[0] <= cutoff]
            if observations:
                price = observations[-1][1]
                coverage += 1
            else:
                price = Decimal(str(position.get("mark_price") or position["average_entry"]))
            marks[instrument] = str(price)
            nav += Decimal(str(position["quantity"])) * price
        days.append(
            {
                "date": cursor.isoformat(),
                "nav": str(nav),
                "cash": str(state["cash"]),
                "position_count": len(positions),
                "code_owned_mark_coverage": str(
                    Decimal(coverage) / Decimal(len(positions)) if positions else Decimal("1")
                ),
                "marks": marks,
            }
        )
        cursor += timedelta(days=1)
    navs = [Decimal(item["nav"]) for item in days]
    peak = max(navs, default=ZERO)
    drawdown = (peak - navs[-1]) / peak if navs and peak > ZERO else ZERO
    return {
        "schema_version": "edgecraft.daily-nav.v1",
        "fund_id": fund_id,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "days": days,
        "peak_nav": str(peak),
        "current_drawdown": str(drawdown),
        "provider_errors": errors,
        "honesty": "Days with incomplete code-owned coverage retain the recorded ledger mark and disclose coverage.",
    }
