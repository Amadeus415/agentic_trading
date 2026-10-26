"""Measured results for the README: ledger extract -> public outcomes -> metrics -> charts.

Three steps, so anyone can rebuild the charts without the private ledger:

1. ``extract`` copies a ledger read-only and writes the numbers the report needs
   (NAV path, fills, journaled forecasts, gate decisions) to ``results/data``. No
   research text, evidence, or source URLs leave the ledger.
2. ``fetch`` reads public outcomes: Polymarket resolutions for every contract the
   agent forecast, and SPY daily closes for the benchmark. No keys are needed.
3. ``report`` turns those committed files into ``results/results.json`` and the
   charts under ``results/charts``. It is offline and deterministic.

The metric helpers at the top are plain functions so they can be tested alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sqlite3
import subprocess  # nosec B404 - fixed git argv, no shell
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from edgecraft.lineage import REPO_ROOT

EXTRACT_SCHEMA = "edgecraft.results-extract.v1"
PUBLIC_SCHEMA = "edgecraft.results-public.v1"
RESULTS_SCHEMA = "edgecraft.results.v1"
ERAS = {"edgecraft-aggressive": "v1", "edgecraft-predictions": "v2", "edgecraft-facts": "v3"}
RESULTS_DIR = REPO_ROOT / "results"
DATA_DIR = RESULTS_DIR / "data"
POLYMARKET_ID = re.compile(r"^polymarket:(\d+):(YES|NO)$")


# --------------------------------------------------------------------------- metrics


def brier_score(probabilities: Sequence[float], outcomes: Sequence[float]) -> float:
    """Mean squared error of probability forecasts against 0/1 outcomes. Lower is better."""
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have the same length")
    if not probabilities:
        raise ValueError("brier_score needs at least one forecast")
    return sum((p - o) ** 2 for p, o in zip(probabilities, outcomes, strict=True)) / len(
        probabilities
    )


def calibration_bins(
    probabilities: Sequence[float], outcomes: Sequence[float], bins: int = 10
) -> list[dict[str, float | int]]:
    """Reliability-diagram rows: equal-width bins with their mean forecast and hit rate.

    Empty bins are omitted. A forecast of exactly 1.0 lands in the top bin.
    """
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have the same length")
    grouped: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for p, o in zip(probabilities, outcomes, strict=True):
        if not 0 <= p <= 1:
            raise ValueError(f"probability {p} is outside [0, 1]")
        grouped[min(int(p * bins), bins - 1)].append((p, o))
    rows = []
    for index in sorted(grouped):
        items = grouped[index]
        rows.append(
            {
                "lower": index / bins,
                "upper": (index + 1) / bins,
                "count": len(items),
                "mean_forecast": sum(p for p, _ in items) / len(items),
                "hit_rate": sum(o for _, o in items) / len(items),
            }
        )
    return rows


def drawdowns(navs: Sequence[float]) -> list[float]:
    """Fractional drop from the running peak at each point (0 at a new high)."""
    peak = float("-inf")
    out = []
    for nav in navs:
        peak = max(peak, nav)
        out.append((peak - nav) / peak if peak > 0 else 0.0)
    return out


def max_drawdown(navs: Sequence[float]) -> dict[str, float | int]:
    """Deepest peak-to-trough drop, with the indexes of that peak and trough."""
    if not navs:
        raise ValueError("max_drawdown needs at least one NAV")
    series = drawdowns(navs)
    trough = max(range(len(series)), key=lambda i: (series[i], -i))
    peak = max(range(trough + 1), key=lambda i: (navs[i], -i))
    return {"depth": series[trough], "peak_index": peak, "trough_index": trough}


def time_weighted_mean(
    times: Sequence[datetime], values: Sequence[float], end: datetime | None = None
) -> float:
    """Average of a step series where each value holds until the next timestamp."""
    if len(times) != len(values) or not times:
        raise ValueError("time_weighted_mean needs matching, non-empty inputs")
    stops = [*times[1:], end or times[-1]]
    weights = [(stop - start).total_seconds() for start, stop in zip(times, stops, strict=True)]
    total = sum(weights)
    if total <= 0:
        return sum(values) / len(values)
    return sum(v * w for v, w in zip(values, weights, strict=True)) / total


def first_theses(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One directional thesis per instrument until it resolves.

    The journal restates an open thesis every cycle (and the monitor copies it
    every hour). Counting each restatement would multiply one belief into dozens
    of "independent" forecasts, so only the first statement is kept until that
    thesis resolves.
    """
    kept: list[dict[str, Any]] = []
    open_until: dict[tuple[str, str], str | None] = {}
    for row in sorted(rows, key=lambda r: r["started_at"]):
        if row["stance"] not in ("long", "short"):
            continue
        key = (row["instrument_id"], row["stance"])
        if key in open_until:
            resolved = open_until[key]
            if resolved is None or row["started_at"] < resolved:
                continue
        open_until[key] = row.get("resolved_at")
        kept.append(row)
    return kept


def first_market_forecasts(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The first settlement-probability forecast per prediction contract.

    Only explicit ``p_win`` counts: early v1 journals used ``confidence`` for
    "will the price reach my target within 72 hours", which is not a
    settlement probability and cannot be compared with the market price.
    """
    seen: set[str] = set()
    out = []
    for row in sorted(rows, key=lambda r: r["started_at"]):
        if (
            row["instrument_id"] in seen
            or row.get("p_source") != "p_win"
            or row.get("market_price") is None
            or row["stance"] == "exit"
        ):
            continue
        seen.add(row["instrument_id"])
        out.append(row)
    return out


# --------------------------------------------------------------------------- extract


def _readonly_copy(source: Path, target: Path) -> Path:
    """Snapshot a live SQLite ledger without writing to it (consistent under WAL)."""
    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def _num(value: Any) -> float | None:
    return None if value is None else float(Decimal(str(value)))


def _extract_fund(ledger: Any, fund_id: str) -> dict[str, Any]:
    from edgecraft.attribution import _round_trips, build_attribution
    from edgecraft.lineage import _attribute, lineage_report, load_deployments

    conn = ledger.connection
    created_at, initial_cash = conn.execute(
        "SELECT created_at, initial_cash FROM funds WHERE fund_id = ?", (fund_id,)
    ).fetchone()
    cycles = ledger.list_full_cycles(fund_id)
    events = ledger.list_events(fund_id)
    verification = ledger.verify(fund_id, raise_on_error=False)
    deployments = load_deployments(REPO_ROOT / "history" / "deployments.json")

    cycle_rows, fills, gate = [], [], []
    quotes_by_cycle: dict[str, dict[str, dict[str, Any]]] = {}
    hypotheses_by_cycle: dict[str, dict[str, dict[str, Any]]] = {}
    risk_checks: Counter[str] = Counter()
    risk_failures: Counter[str] = Counter()
    for cycle in cycles:
        key = cycle["cycle_key"]
        audit = cycle.get("audit") or {}
        runtime = audit.get("runtime") or {}
        state = cycle["state"]
        revision, basis = _attribute(cycle, deployments)
        monitor = runtime.get("model") == "code-only-monitor" or key.startswith("monitor-")
        cycle_rows.append(
            {
                "cycle_key": key,
                "as_of": state["as_of"],
                "kind": "monitor" if monitor else "research",
                "action": cycle["action"],
                "model": runtime.get("model"),
                "revision": revision,
                "revision_basis": basis,
                "nav": _num(state["nav"]),
                "cash": _num(state["cash"]),
                "gross_exposure": _num(state["gross_exposure"]),
                "net_exposure": _num(state["net_exposure"]),
                "open_positions": len(state.get("positions") or []),
            }
        )
        quotes_by_cycle[key] = {q["instrument_id"]: q for q in cycle.get("quotes") or []}
        hypotheses_by_cycle[key] = {
            h["instrument_id"]: h
            for h in (cycle["decision"].get("journal") or {}).get("hypotheses", [])
        }
        for fill in [*(cycle.get("fills") or []), *(cycle.get("settlements") or [])]:
            fills.append(
                {
                    "cycle_key": key,
                    "as_of": state["as_of"],
                    "instrument_id": fill["instrument_id"],
                    "asset_class": fill["asset_class"],
                    "side": fill["side"],
                    "quantity": _num(fill["quantity"]),
                    "quote_price": _num(fill.get("quote_price")),
                    "execution_price": _num(fill.get("execution_price")),
                    "fee": _num(fill.get("fee")),
                    "realized_pnl": _num(fill.get("realized_pnl")),
                    "is_settlement": bool(fill.get("is_settlement")),
                }
            )
        for check in (audit.get("risk") or {}).get("checks") or []:
            name = check["name"].split(":", 1)[0]
            risk_checks[name] += 1
            if not check["passed"]:
                risk_failures[name] += 1
        sizing = audit.get("sizing") or {}
        for decision, items in (
            ("accepted", sizing.get("accepted")),
            ("dropped", sizing.get("dropped")),
        ):
            for item in items or []:
                reason = item.get("reason") or "sized"
                gate.append(
                    {
                        "cycle_key": key,
                        "as_of": state["as_of"],
                        "instrument_id": item["instrument_id"],
                        "gate": decision,
                        "reason": reason,
                        "p_win": _num(item.get("p_win")),
                        "expected_return": _num(item.get("expected_return")),
                        "minimum": _num(item.get("minimum")),
                        "kelly_weight": _num(item.get("kelly_weight")),
                        "notional": _num(item.get("notional")),
                        "playbook_id": item.get("playbook_id"),
                    }
                )

    theses = []
    for row in build_attribution(ledger, fund_id):
        quote = quotes_by_cycle.get(row["cycle_key"], {}).get(row["instrument_id"])
        raw = hypotheses_by_cycle.get(row["cycle_key"], {}).get(row["instrument_id"], {})
        prediction = row["instrument_id"].startswith(("polymarket:", "kalshi:"))
        theses.append(
            {
                "cycle_key": row["cycle_key"],
                "instrument_id": row["instrument_id"],
                "asset_class": "prediction" if prediction else row["asset_class"],
                "stance": row["stance"],
                "playbook_id": row["playbook_id"],
                "model": row["model"],
                "started_at": row["started_at"],
                "deadline": row["deadline"],
                "resolved_at": row["resolved_at"],
                "outcome": row["outcome"],
                "won": row["won"],
                "scored": row["scored"],
                "p": _num(row["p_win"]),
                "p_source": "p_win" if raw.get("p_win") is not None else "confidence",
                "market_price": _num(quote["price"]) if prediction and quote else None,
            }
        )

    rejected = [
        {
            "occurred_at": event.occurred_at.isoformat().replace("+00:00", "Z"),
            "cycle_key": event.payload.get("cycle_key"),
            "error_type": event.payload.get("error_type"),
            "reason": event.payload.get("reason"),
        }
        for event in events
        if event.event_type == "cycle_rejected"
    ]
    retired = [e for e in events if e.event_type == "fund_retired"]
    lineage = lineage_report(
        fund_id=fund_id,
        initial_cash=Decimal(initial_cash),
        cycles=cycles,
        deployments=deployments,
    )
    return {
        "era": ERAS.get(fund_id, "other"),
        "created_at": created_at,
        "initial_cash": float(Decimal(initial_cash)),
        "retired_at": retired[0].occurred_at.isoformat().replace("+00:00", "Z")
        if retired
        else None,
        "verification": verification.model_dump(mode="json"),
        "chain_head": events[-1].event_hash if events else None,
        "event_counts": dict(sorted(Counter(e.event_type for e in events).items())),
        "risk_checks": {
            "evaluated": sum(risk_checks.values()),
            "failed": sum(risk_failures.values()),
            "by_name": dict(sorted(risk_checks.items())),
            "failed_by_name": dict(sorted(risk_failures.items())),
        },
        "rejected_cycles": rejected,
        "cycles": cycle_rows,
        "fills": fills,
        "round_trips": [
            {
                "instrument_id": t["instrument_id"],
                "asset_class": t["asset_class"],
                "side": t["side"],
                "opened_at": t["opened_at"],
                "closed_at": t["closed_at"],
                "hold_hours": _num(t["hold_hours"]),
                "realized_pnl_after_cost": _num(t["realized_pnl_after_cost"]),
            }
            for t in _round_trips(cycles)
        ],
        "theses": theses,
        "gate": gate,
        "lineage": [
            {
                **{
                    k: segment[k]
                    for k in ("revision", "basis", "started_at", "ended_at", "cycles", "fills")
                },
                **{k: _num(segment[k]) for k in ("start_nav", "end_nav", "nav_change")},
            }
            for segment in lineage["segments"]
        ],
    }


def extract_ledger(ledger_path: Path) -> dict[str, Any]:
    """Read every fund in a ledger through a private read-only snapshot."""
    from edgecraft.paper_fund import PaperFundLedger

    if not ledger_path.exists():
        raise FileNotFoundError(ledger_path)
    with tempfile.TemporaryDirectory() as tmp:
        copy = _readonly_copy(ledger_path, Path(tmp) / "ledger.db")
        with PaperFundLedger(copy) as ledger:
            fund_ids = [
                row[0]
                for row in ledger.connection.execute(
                    "SELECT fund_id FROM funds ORDER BY created_at"
                )
            ]
            funds = {fund_id: _extract_fund(ledger, fund_id) for fund_id in fund_ids}
    return {
        "schema_version": EXTRACT_SCHEMA,
        "extracted_at": _now(),
        "ledger_file": ledger_path.name,
        "note": "Numbers only. Research text, evidence, and source URLs stay in the private ledger.",
        "funds": funds,
    }


# --------------------------------------------------------------------------- public data


def _polymarket_resolution(market_id: str) -> dict[str, Any]:
    from edgecraft.marketdata import _get_json

    market = _get_json(f"https://gamma-api.polymarket.com/markets/{market_id}")

    def array(value: Any) -> list[Any]:
        return json.loads(value) if isinstance(value, str) else list(value or [])

    labels = [str(label).upper() for label in array(market.get("outcomes"))]
    prices = [float(p) for p in array(market.get("outcomePrices"))]
    return {
        "question": market.get("question"),
        "end_date": market.get("endDate"),
        "closed": bool(market.get("closed")),
        "uma_resolution_status": market.get("umaResolutionStatus"),
        "outcome_prices": dict(zip(labels, prices, strict=False)),
    }


def _spy_daily(start: datetime, end: datetime) -> list[dict[str, Any]]:
    from edgecraft.marketdata import _get_json

    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/SPY"
        f"?interval=1d&period1={int(start.timestamp())}&period2={int(end.timestamp())}"
    )
    payload = _get_json(url)["chart"]["result"][0]
    closes = payload["indicators"]["quote"][0]["close"]
    adjusted = payload["indicators"]["adjclose"][0]["adjclose"]
    return [
        {
            "date": datetime.fromtimestamp(stamp, UTC).date().isoformat(),
            "close": close,
            "adjclose": adj,
        }
        for stamp, close, adj in zip(payload["timestamp"], closes, adjusted, strict=True)
        if close is not None and adj is not None
    ]


def fetch_public(extract: dict[str, Any]) -> dict[str, Any]:
    """Fetch public outcomes for every contract the extract mentions, plus SPY."""
    market_ids = sorted(
        {
            match.group(1)
            for fund in extract["funds"].values()
            for row in [*fund["theses"], *fund["fills"]]
            if (match := POLYMARKET_ID.match(row["instrument_id"]))
        },
        key=int,
    )
    resolutions = {market_id: _polymarket_resolution(market_id) for market_id in market_ids}
    stamps = [_dt(row["as_of"]) for fund in extract["funds"].values() for row in fund["cycles"]]
    spy: list[dict[str, Any]] = []
    if stamps:
        spy = _spy_daily(min(stamps) - timedelta(days=7), max(stamps) + timedelta(days=3))
    return {
        "schema_version": PUBLIC_SCHEMA,
        "fetched_at": _now(),
        "sources": {
            "polymarket": "https://gamma-api.polymarket.com/markets/<id>",
            "spy": "https://query1.finance.yahoo.com/v8/finance/chart/SPY (daily, adjclose includes dividends)",
        },
        "polymarket": resolutions,
        "spy_daily": spy,
    }


# --------------------------------------------------------------------------- report


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _close_time(day: str) -> datetime:
    """When a US equity session that trades on ``day`` closes, in UTC."""
    local = datetime.fromisoformat(day).replace(hour=16, tzinfo=ZoneInfo("America/New_York"))
    return local.astimezone(UTC)


def resolved_outcome(instrument_id: str, public: dict[str, Any]) -> float | None:
    """1.0 or 0.0 once Polymarket confirms resolution of this outcome token, else None."""
    match = POLYMARKET_ID.match(instrument_id)
    if not match:
        return None
    market = public.get("polymarket", {}).get(match.group(1))
    if not market or not market["closed"] or market["uma_resolution_status"] != "resolved":
        return None
    price = market["outcome_prices"].get(match.group(2))
    return price if price in (0.0, 1.0) else None


def _equity(fund: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    start = fund["initial_cash"]
    points = [{"at": fund["created_at"], "nav": start}] + [
        {"at": c["as_of"], "nav": c["nav"]} for c in fund["cycles"]
    ]
    navs = [p["nav"] for p in points]
    deep = max_drawdown(navs)
    peak = max(range(len(navs)), key=lambda i: navs[i])
    first, last = _dt(fund["cycles"][0]["as_of"]), _dt(fund["cycles"][-1]["as_of"])

    # SPY total return over the same window: the last close before the first
    # cycle to the last close before the final cycle (closes are 4 pm New York).
    spy = [row for row in public.get("spy_daily", []) if row["adjclose"]]
    before_first = [r for r in spy if _close_time(r["date"]) < first]
    through_last = [r for r in spy if _close_time(r["date"]) <= last]
    benchmark = None
    if before_first and through_last:
        base, final = before_first[-1], through_last[-1]
        benchmark = {
            "start_date": base["date"],
            "end_date": final["date"],
            "total_return": final["adjclose"] / base["adjclose"] - 1,
            "price_return": final["close"] / base["close"] - 1,
            "series": [
                {"date": r["date"], "nav": start * r["adjclose"] / base["adjclose"]}
                for r in spy
                if base["date"] <= r["date"] <= final["date"]
            ],
        }
    return {
        "start_nav": start,
        "end_nav": navs[-1],
        "return": navs[-1] / start - 1,
        "peak_nav": navs[peak],
        "peak_at": points[peak]["at"],
        "max_drawdown": deep["depth"],
        "max_drawdown_peak_at": points[int(deep["peak_index"])]["at"],
        "max_drawdown_trough_at": points[int(deep["trough_index"])]["at"],
        "max_drawdown_trough_nav": navs[int(deep["trough_index"])],
        "first_cycle_at": fund["cycles"][0]["as_of"],
        "last_cycle_at": fund["cycles"][-1]["as_of"],
        "points": [{**p, "drawdown": d} for p, d in zip(points, drawdowns(navs), strict=True)],
        "spy": benchmark,
    }


def _question(instrument_id: str, public: dict[str, Any]) -> str | None:
    match = POLYMARKET_ID.match(instrument_id)
    market = public.get("polymarket", {}).get(match.group(1)) if match else None
    return market.get("question") if market else None


def _trades(fund: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    trips = [
        trip | {"question": _question(trip["instrument_id"], public)}
        for trip in fund["round_trips"]
    ]
    # Before Python owned sizing, the agent chose its own quantities.
    since = min((row["as_of"] for row in fund["gate"]), default=None)
    by_sizer: dict[str, list[float]] = defaultdict(list)
    for trip in trips:
        sizer = "python" if since and trip["opened_at"] >= since else "agent"
        by_sizer[sizer].append(trip["realized_pnl_after_cost"])
    pnl = [t["realized_pnl_after_cost"] for t in trips]
    by_class: dict[str, list[float]] = defaultdict(list)
    for trip in trips:
        by_class[trip["asset_class"]].append(trip["realized_pnl_after_cost"])
    wins = [v for v in pnl if v > 0]
    losses = [-v for v in pnl if v < 0]
    return {
        "closed": len(trips),
        "wins": len(wins),
        "realized_pnl_after_cost": sum(pnl),
        "profit_factor": sum(wins) / sum(losses) if losses else None,
        "fees": sum(f["fee"] or 0 for f in fund["fills"]),
        "fills": sum(not f["is_settlement"] for f in fund["fills"]),
        "settlements": sum(f["is_settlement"] for f in fund["fills"]),
        "by_asset_class": {
            name: {
                "closed": len(values),
                "wins": sum(v > 0 for v in values),
                "realized_pnl_after_cost": sum(values),
            }
            for name, values in sorted(by_class.items())
        },
        "by_sizer": {
            "python_sizing_since": since,
            **{
                name: {"closed": len(values), "realized_pnl_after_cost": sum(values)}
                for name, values in sorted(by_sizer.items())
            },
        },
        "median_hold_hours": sorted(t["hold_hours"] for t in trips)[len(trips) // 2]
        if trips
        else None,
        "round_trips": sorted(trips, key=lambda t: t["realized_pnl_after_cost"]),
    }


def _gate(fund: dict[str, Any]) -> dict[str, Any]:
    """What deterministic code did with the agent's proposals."""
    gate = fund["gate"]
    sized_cycles = sorted({row["cycle_key"] for row in gate})
    window_start = min((row["as_of"] for row in gate), default=None)
    entries = [row for row in gate if row["reason"] != "inventory_exit"]
    reasons = Counter(row["reason"] for row in entries)
    theses_in_window = [
        t
        for t in fund["theses"]
        if window_start and t["started_at"] >= window_start and t["cycle_key"] in sized_cycles
    ]
    research_cycles = [c for c in fund["cycles"] if c["kind"] == "research"]
    return {
        "python_sizing_since": window_start,
        "cycles_with_sizing": len(sized_cycles),
        "hypotheses_journaled": len(theses_in_window),
        "agent_rejected_flat": sum(t["stance"] == "flat" for t in theses_in_window),
        "entry_candidates": len(entries),
        "sized": reasons.get("sized", 0),
        "blocked": len(entries) - reasons.get("sized", 0),
        "blocked_share": (len(entries) - reasons.get("sized", 0)) / len(entries)
        if entries
        else None,
        "reasons": dict(reasons.most_common()),
        "inventory_exits": sum(row["reason"] == "inventory_exit" for row in gate),
        "risk_checks": fund["risk_checks"],
        "rejected_cycles": fund["rejected_cycles"],
        "mark_fetch_alerts": fund["event_counts"].get("alert_mark_fetch_failed", 0),
        "research_cycles": len(research_cycles),
        "monitor_cycles": len(fund["cycles"]) - len(research_cycles),
        "trade_cycles": sum(c["action"] == "trade" for c in fund["cycles"]),
    }


def _forecasts(fund: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    """Agent probability vs the market price at the same moment, on resolved contracts."""
    rows = []
    for row in first_market_forecasts(
        t for t in fund["theses"] if t["asset_class"] == "prediction"
    ):
        outcome = resolved_outcome(row["instrument_id"], public)
        rows.append(
            {
                "instrument_id": row["instrument_id"],
                "question": _question(row["instrument_id"], public),
                "forecast_at": row["started_at"],
                "stance": row["stance"],
                "agent_p": row["p"],
                "market_p": row["market_price"],
                "edge": row["p"] - row["market_price"],
                "outcome": outcome,
                "agent_brier": (row["p"] - outcome) ** 2 if outcome is not None else None,
                "market_brier": (row["market_price"] - outcome) ** 2
                if outcome is not None
                else None,
            }
        )
    resolved = [r for r in rows if r["outcome"] is not None]
    summary: dict[str, Any] = {"forecasts": len(rows), "resolved": len(resolved)}
    if resolved:
        agent = brier_score([r["agent_p"] for r in resolved], [r["outcome"] for r in resolved])
        market = brier_score([r["market_p"] for r in resolved], [r["outcome"] for r in resolved])
        closer = sum(r["agent_brier"] < r["market_brier"] for r in resolved)
        worse = sum(r["agent_brier"] > r["market_brier"] for r in resolved)
        best = max(resolved, key=lambda r: r["market_brier"] - r["agent_brier"])
        rest = [r for r in resolved if r is not best]
        summary |= {
            "agent_brier": agent,
            "market_brier": market,
            "agent_closer": closer,
            "market_closer": worse,
            "ties": len(resolved) - closer - worse,
            "largest_single_gain": {
                "instrument_id": best["instrument_id"],
                "brier_gain": best["market_brier"] - best["agent_brier"],
            },
            "without_largest_gain": {
                "agent_brier": brier_score(
                    [r["agent_p"] for r in rest], [r["outcome"] for r in rest]
                )
                if rest
                else None,
                "market_brier": brier_score(
                    [r["market_p"] for r in rest], [r["outcome"] for r in rest]
                )
                if rest
                else None,
            },
        }
    return {"summary": summary, "contracts": rows}


def _calibration(fund: dict[str, Any]) -> dict[str, Any]:
    """Stated probability vs how often the thesis won, one row per thesis episode."""
    theses = [t for t in first_theses(fund["theses"]) if t["scored"]]
    rows = calibration_bins([t["p"] for t in theses], [1.0 if t["won"] else 0.0 for t in theses])
    by_class = Counter(t["asset_class"] for t in theses)
    return {
        "theses": len(theses),
        "journaled_hypotheses": len(fund["theses"]),
        "by_asset_class": dict(sorted(by_class.items())),
        "mean_stated": sum(t["p"] for t in theses) / len(theses) if theses else None,
        "win_rate": sum(t["won"] for t in theses) / len(theses) if theses else None,
        "brier": brier_score([t["p"] for t in theses], [1.0 if t["won"] else 0.0 for t in theses])
        if theses
        else None,
        "bins": rows,
        "definition": "A thesis wins if its target is hit, or it is closed at a profit, before its "
        "stop or deadline. Restatements of an open thesis are dropped.",
    }


def _exposure(fund: dict[str, Any]) -> dict[str, Any]:
    cycles = fund["cycles"]
    times = [_dt(c["as_of"]) for c in cycles]
    gross = [c["gross_exposure"] / c["nav"] for c in cycles]
    return {
        "time_weighted_gross_exposure": time_weighted_mean(times, gross),
        "max_gross_exposure": max(gross),
        "share_of_time_flat": time_weighted_mean(
            times, [1.0 if c["open_positions"] == 0 else 0.0 for c in cycles]
        ),
        "series": [
            {"at": c["as_of"], "gross_exposure": g, "open_positions": c["open_positions"]}
            for c, g in zip(cycles, gross, strict=True)
        ],
    }


def _models(fund: dict[str, Any]) -> dict[str, int]:
    return dict(
        Counter(c["model"] or "not recorded" for c in fund["cycles"] if c["kind"] == "research")
    )


def _git_revision() -> str | None:
    try:
        head = subprocess.run(  # nosec B603 B607 - fixed git argv
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(  # nosec B603 B607 - fixed git argv
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", "src"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return f"{head}+dirty" if dirty else head


def _machine() -> str:
    try:
        chip = subprocess.run(  # nosec B603 B607 - fixed argv
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        chip = platform.processor() or platform.machine()
    system = (
        f"macOS {platform.mac_ver()[0]}" if platform.system() == "Darwin" else platform.system()
    )
    return f"{chip}, {system}, Python {platform.python_version()}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_results(
    extract: dict[str, Any], public: dict[str, Any], inputs: dict[str, str] | None = None
) -> dict[str, Any]:
    funds: dict[str, Any] = {}
    for fund_id, fund in extract["funds"].items():
        base = {
            "fund_id": fund_id,
            "era": fund["era"],
            "created_at": fund["created_at"],
            "retired_at": fund["retired_at"],
            "initial_cash": fund["initial_cash"],
            "cycles": len(fund["cycles"]),
            "verification": fund["verification"],
        }
        if not fund["cycles"]:
            funds[fund["era"]] = base | {"status": "no completed cycles yet"}
            continue
        funds[fund["era"]] = base | {
            "status": "retired" if fund["retired_at"] else "active",
            "equity": _equity(fund, public),
            "trades": _trades(fund, public),
            "gate": _gate(fund),
            "forecasts": _forecasts(fund, public),
            "calibration": _calibration(fund),
            "exposure": _exposure(fund),
            "research_models": _models(fund),
            "lineage": fund["lineage"],
        }
    return {
        "schema_version": RESULTS_SCHEMA,
        "generated_at": _now(),
        "as_of": extract["extracted_at"],
        "public_data_fetched_at": public.get("fetched_at"),
        "code_revision": _git_revision(),
        "machine": _machine(),
        "inputs": inputs or {},
        "paper_money_only": True,
        "funds": funds,
    }


# --------------------------------------------------------------------------- CLI


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m edgecraft.results", description=__doc__)
    steps = parser.add_subparsers(dest="step", required=True)
    extract = steps.add_parser("extract", help="Snapshot a ledger read-only into results/data.")
    extract.add_argument("--ledger", type=Path, required=True)
    steps.add_parser("fetch", help="Fetch public resolutions and SPY closes into results/data.")
    report = steps.add_parser("report", help="Build results.json and charts from results/data.")
    report.add_argument("--no-charts", action="store_true")
    args = parser.parse_args(argv)

    extract_path = DATA_DIR / "ledger-extract.json"
    public_path = DATA_DIR / "public-data.json"
    if args.step == "extract":
        _write_json(extract_path, extract_ledger(args.ledger))
        print(f"wrote {extract_path.relative_to(REPO_ROOT)}")
    elif args.step == "fetch":
        payload = json.loads(extract_path.read_text(encoding="utf-8"))
        _write_json(public_path, fetch_public(payload))
        print(f"wrote {public_path.relative_to(REPO_ROOT)}")
    else:
        results = build_results(
            json.loads(extract_path.read_text(encoding="utf-8")),
            json.loads(public_path.read_text(encoding="utf-8")),
            inputs={str(p.relative_to(REPO_ROOT)): _sha256(p) for p in (extract_path, public_path)},
        )
        _write_json(RESULTS_DIR / "results.json", results)
        print("wrote results/results.json")
        if not args.no_charts:
            from edgecraft.results_charts import render_all

            for path in render_all(results, RESULTS_DIR / "charts"):
                print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
