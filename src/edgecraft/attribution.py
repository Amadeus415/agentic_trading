"""Ledger-derived hypothesis attribution and fund performance reporting.

The module is deliberately read-only. It treats the immutable cycle packets as
the observation set and never invents intracycle prices that the ledger did not
record.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from edgecraft.paper_fund import FundMandate, PaperFundLedger

ZERO = Decimal("0")
ONE = Decimal("1")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _dec(value: Any, default: Decimal = ZERO) -> Decimal:
    if value is None:
        return default
    return Decimal(str(value))


def _bucket(value: Decimal) -> str:
    lower = min(9, max(0, int(value * 10))) * 10
    return f"{lower:02d}-{lower + 10:02d}%"


def _horizon_bucket(hours: int) -> str:
    if hours <= 8:
        return "1-8h"
    if hours <= 24:
        return "9-24h"
    if hours <= 72:
        return "25-72h"
    return "73h+"


def _slot(cycle_key: str) -> str:
    for value in ("session-eu", "session-us-open", "session-us-close", "session-offhours"):
        if value in cycle_key:
            return value
    return "manual"


def _hit(price: Decimal, level: Decimal | None, *, above: bool) -> bool:
    if level is None:
        return False
    return price >= level if above else price <= level


def _outcome_for_hypothesis(
    *,
    cycle_index: int,
    cycle: dict[str, Any],
    hypothesis: dict[str, Any],
    cycles: list[dict[str, Any]],
) -> dict[str, Any]:
    instrument = str(hypothesis["instrument_id"])
    stance = str(hypothesis["stance"])
    started = _dt(str(cycle["as_of"]))
    horizon_hours = int(hypothesis["expected_horizon_hours"])
    deadline = started + timedelta(hours=horizon_hours)
    target = _dec(hypothesis.get("target_price")) if hypothesis.get("target_price") else None
    stop = (
        _dec(hypothesis.get("invalidation_price")) if hypothesis.get("invalidation_price") else None
    )

    observations: list[tuple[datetime, Decimal]] = []
    related_fills: list[tuple[datetime, dict[str, Any]]] = []
    asset_class = "unknown"
    model = None
    prompt_version = None
    for later in cycles[cycle_index:]:
        observed_cycle_at = _dt(str(later["as_of"]))
        for quote in later.get("quotes", []):
            if str(quote.get("instrument_id")) != instrument:
                continue
            asset_class = str(quote.get("asset_class", asset_class))
            observations.append((_dt(str(quote["observed_at"])), _dec(quote["price"])))
        for fill in [*later.get("fills", []), *later.get("settlements", [])]:
            if str(fill.get("instrument_id")) == instrument:
                asset_class = str(fill.get("asset_class", asset_class))
                related_fills.append((observed_cycle_at, fill))
        if later is cycle:
            runtime = (later.get("audit") or {}).get("runtime") or {}
            model = runtime.get("model")
            prompt_version = runtime.get("prompt_version")

    observations.sort(key=lambda item: item[0])
    in_window = [item for item in observations if started <= item[0] <= deadline]
    relevant = in_window or [item for item in observations if item[0] >= started][:1]
    entry_price = relevant[0][1] if relevant else None

    target_hit_at: datetime | None = None
    stop_hit_at: datetime | None = None
    if stance in {"long", "short"}:
        target_above = stance == "long"
        stop_above = stance == "short"
        for observed_at, price in in_window:
            if target_hit_at is None and _hit(price, target, above=target_above):
                target_hit_at = observed_at
            if stop_hit_at is None and _hit(price, stop, above=stop_above):
                stop_hit_at = observed_at

    closes = [
        (at, fill)
        for at, fill in related_fills
        if at >= started and str(fill.get("side")) in {"sell", "cover", "settle"}
    ]
    close_at = closes[0][0] if closes else None
    realized = sum((_dec(fill.get("realized_pnl")) for _, fill in closes), ZERO)
    fees = sum((_dec(fill.get("fee")) for _, fill in related_fills if _ >= started), ZERO)

    terminal: list[tuple[datetime, str]] = []
    if target_hit_at:
        terminal.append((target_hit_at, "target_hit"))
    if stop_hit_at:
        terminal.append((stop_hit_at, "stop_hit"))
    if close_at:
        terminal.append((close_at, "manually_closed"))
    if observations and observations[-1][0] >= deadline:
        terminal.append((deadline, "expired"))
    terminal.sort(key=lambda item: (item[0], item[1]))
    outcome = terminal[0][1] if terminal else "open"
    resolved_at = terminal[0][0] if terminal else None

    prices = [price for _, price in in_window]
    mfe = mae = None
    if entry_price is not None and prices and entry_price != ZERO and stance in {"long", "short"}:
        signed = ONE if stance == "long" else -ONE
        excursions = [signed * ((price / entry_price) - ONE) for price in prices]
        mfe = max(excursions)
        mae = min(excursions)

    won = outcome == "target_hit" or (outcome == "manually_closed" and realized > ZERO)
    lost = outcome == "stop_hit" or (outcome == "manually_closed" and realized < ZERO)
    scored = outcome != "open" and (won or lost or outcome == "expired")
    return {
        "hypothesis_id": f"{cycle['cycle_key']}:{instrument}",
        "cycle_key": cycle["cycle_key"],
        "instrument_id": instrument,
        "asset_class": asset_class,
        "stance": stance,
        "driver": hypothesis.get("driver", "untagged"),
        "playbook_id": hypothesis.get("playbook_id", "unassigned"),
        "session_slot": _slot(str(cycle["cycle_key"])),
        "horizon_bucket": _horizon_bucket(horizon_hours),
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "deadline": deadline.isoformat().replace("+00:00", "Z"),
        "resolved_at": resolved_at.isoformat().replace("+00:00", "Z") if resolved_at else None,
        "outcome": outcome,
        "won": won,
        "lost": lost,
        "scored": scored,
        "p_win": str(hypothesis.get("p_win", hypothesis.get("confidence", "0"))),
        "confidence_bucket": _bucket(
            _dec(hypothesis.get("p_win", hypothesis.get("confidence", "0")))
        ),
        "target_price": str(target) if target is not None else None,
        "invalidation_price": str(stop) if stop is not None else None,
        "realized_pnl_after_cost": str(realized),
        "fees": str(fees),
        "hold_hours": (
            str(Decimal(str((resolved_at - started).total_seconds() / 3600)))
            if resolved_at
            else None
        ),
        "mfe": str(mfe) if mfe is not None else None,
        "mae": str(mae) if mae is not None else None,
        "model": model or "unknown",
        "prompt_version": prompt_version or "unknown",
        "observation_count": len(in_window),
    }


def build_attribution(ledger: PaperFundLedger, fund_id: str) -> list[dict[str, Any]]:
    """Score every journaled hypothesis against later ledger marks."""
    cycles = ledger.list_full_cycles(fund_id)
    rows: list[dict[str, Any]] = []
    for index, cycle in enumerate(cycles):
        journal = cycle["decision"].get("journal") or {}
        for hypothesis in journal.get("hypotheses", []):
            rows.append(
                _outcome_for_hypothesis(
                    cycle_index=index,
                    cycle=cycle,
                    hypothesis=hypothesis,
                    cycles=cycles,
                )
            )
    return rows


def _aggregate(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    scored = [row for row in rows if row["scored"]]
    wins = [row for row in scored if row["won"]]
    pnl = [_dec(row["realized_pnl_after_cost"]) for row in rows]
    gains = sum((value for value in pnl if value > ZERO), ZERO)
    losses = abs(sum((value for value in pnl if value < ZERO), ZERO))
    return {
        "hypotheses": len(rows),
        "scored": len(scored),
        "wins": len(wins),
        "hit_rate": str(Decimal(len(wins)) / Decimal(len(scored))) if scored else None,
        "expectancy_after_cost": str(sum(pnl, ZERO) / Decimal(len(scored))) if scored else None,
        "realized_pnl_after_cost": str(sum(pnl, ZERO)),
        "profit_factor": str(gains / losses) if losses else ("Infinity" if gains else None),
    }


def _round_trips(cycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair opening and closing inventory and allocate opening fees once."""
    inventory: dict[str, dict[str, Any]] = {}
    trips: list[dict[str, Any]] = []
    for cycle in cycles:
        journal = cycle["decision"].get("journal") or {}
        hypotheses = {str(item["instrument_id"]): item for item in journal.get("hypotheses", [])}
        runtime = (cycle.get("audit") or {}).get("runtime") or {}
        at = _dt(str(cycle["as_of"]))
        for fill in [*cycle.get("fills", []), *cycle.get("settlements", [])]:
            instrument = str(fill["instrument_id"])
            side = str(fill["side"])
            quantity = _dec(fill["quantity"])
            fee = _dec(fill["fee"])
            if side in {"buy", "short"}:
                row = inventory.setdefault(
                    instrument,
                    {
                        "quantity": ZERO,
                        "opening_fees": ZERO,
                        "opened_at": at,
                        "side": "long" if side == "buy" else "short",
                        "asset_class": fill["asset_class"],
                        "session_slot": _slot(str(cycle["cycle_key"])),
                        "model": runtime.get("model") or "unknown",
                        "playbook_id": hypotheses.get(instrument, {}).get(
                            "playbook_id", "unassigned"
                        ),
                    },
                )
                row["quantity"] += quantity
                row["opening_fees"] += fee
                continue
            if side not in {"sell", "cover", "settle"} or instrument not in inventory:
                continue
            row = inventory[instrument]
            open_quantity = _dec(row["quantity"])
            allocated_quantity = min(quantity, open_quantity)
            opening_fee = (
                _dec(row["opening_fees"]) * allocated_quantity / open_quantity
                if open_quantity
                else ZERO
            )
            net = _dec(fill["realized_pnl"]) - opening_fee
            trips.append(
                {
                    "instrument_id": instrument,
                    "asset_class": row["asset_class"],
                    "side": row["side"],
                    "playbook_id": row["playbook_id"],
                    "session_slot": row["session_slot"],
                    "model": row["model"],
                    "opened_at": row["opened_at"].isoformat().replace("+00:00", "Z"),
                    "closed_at": at.isoformat().replace("+00:00", "Z"),
                    "hold_hours": str(Decimal(str((at - row["opened_at"]).total_seconds() / 3600))),
                    "quantity": str(allocated_quantity),
                    "realized_pnl_after_cost": str(net),
                    "won": net > ZERO,
                    "lost": net < ZERO,
                }
            )
            remaining = open_quantity - allocated_quantity
            if remaining <= ZERO:
                del inventory[instrument]
            else:
                row["quantity"] = remaining
                row["opening_fees"] = _dec(row["opening_fees"]) - opening_fee
    return trips


def _aggregate_trades(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnl = [_dec(row["realized_pnl_after_cost"]) for row in rows]
    wins = sum(value > ZERO for value in pnl)
    gains = sum((value for value in pnl if value > ZERO), ZERO)
    losses = abs(sum((value for value in pnl if value < ZERO), ZERO))
    return {
        "closed_trades": len(rows),
        "wins": wins,
        "hit_rate": str(Decimal(wins) / Decimal(len(rows))) if rows else None,
        "expectancy_after_cost": str(sum(pnl, ZERO) / Decimal(len(rows))) if rows else None,
        "realized_pnl_after_cost": str(sum(pnl, ZERO)),
        "profit_factor": str(gains / losses) if losses else ("Infinity" if gains else None),
    }


def _group(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key, "unknown"))].append(row)
    return {name: _aggregate(items) for name, items in sorted(grouped.items())}


def _sharpe(navs: list[Decimal]) -> str | None:
    returns = [float((b / a) - ONE) for a, b in zip(navs, navs[1:], strict=False) if a]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    if variance <= 0:
        return None
    return str(Decimal(str((mean / math.sqrt(variance)) * math.sqrt(252))))


def _expectancy_interval(trades: list[dict[str, Any]]) -> tuple[Decimal | None, Decimal | None]:
    values = [float(_dec(item["realized_pnl_after_cost"])) for item in trades]
    if len(values) < 2:
        return None, None
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / (len(values) - 1)
    margin = 1.96 * math.sqrt(variance / len(values))
    return Decimal(str(mean - margin)), Decimal(str(mean + margin))


def _calibration(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["scored"]:
            grouped[row["confidence_bucket"]].append(row)
    output = []
    for bucket, items in sorted(grouped.items()):
        stated = sum((_dec(item["p_win"]) for item in items), ZERO) / Decimal(len(items))
        realized = Decimal(sum(bool(item["won"]) for item in items)) / Decimal(len(items))
        output.append(
            {
                "bucket": bucket,
                "count": len(items),
                "mean_stated_p_win": str(stated),
                "realized_win_rate": str(realized),
                "calibration_error": str(abs(stated - realized)),
            }
        )
    return output


def build_fund_report(
    ledger: PaperFundLedger, fund_id: str, mandate: FundMandate
) -> dict[str, Any]:
    """Build the read-only performance and attribution report used by CLI/UI."""
    rows = build_attribution(ledger, fund_id)
    cycles = ledger.list_full_cycles(fund_id)
    trades = _round_trips(cycles)
    history = ledger.state_history(fund_id)
    navs = [mandate.initial_cash, *(_dec(item["nav"]) for item in history)]
    fills = [fill for cycle in cycles for fill in cycle["fills"]]
    total_fees = sum((_dec(fill["fee"]) for fill in fills), ZERO)
    model_cost = sum(
        (
            _dec(((cycle.get("audit") or {}).get("runtime") or {}).get("model_cost_usd"))
            for cycle in cycles
        ),
        ZERO,
    )
    deployed = sum((_dec(item["gross_exposure"]) for item in history), ZERO)
    nav_change = navs[-1] - navs[0]
    calibration = _calibration(rows)
    expectancy_low, expectancy_high = _expectancy_interval(trades)
    sharpe = _sharpe(navs)
    max_calibration_error = max(
        (_dec(item["calibration_error"]) for item in calibration), default=ONE
    )
    gross_profit = sum(
        (max(ZERO, _dec(trade["realized_pnl_after_cost"])) for trade in trades), ZERO
    )
    cost_share = model_cost / gross_profit if gross_profit else None
    return {
        "schema_version": "edgecraft.fund-report.v1",
        "fund_id": fund_id,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "summary": {
            **_aggregate_trades(trades),
            "hypotheses": len(rows),
            "scored_hypotheses": sum(bool(row["scored"]) for row in rows),
            "cycles": len(history),
            "fills": len(fills),
            "fees": str(total_fees),
            "model_cost_usd": str(model_cost),
            "model_cost_share_of_gross_profit": str(cost_share) if cost_share is not None else None,
            "nav": str(navs[-1]),
            "nav_change": str(nav_change),
            "sharpe_cycle_annualized": sharpe,
            "expectancy_95_interval": [
                str(expectancy_low) if expectancy_low is not None else None,
                str(expectancy_high) if expectancy_high is not None else None,
            ],
            "exposure_weighted_return": str(nav_change / deployed) if deployed else None,
        },
        "calibration": calibration,
        "cuts": {
            key: _group(rows, key)
            for key in (
                "asset_class",
                "stance",
                "session_slot",
                "horizon_bucket",
                "model",
                "playbook_id",
            )
        },
        "benchmarks": {
            "spy_buy_and_hold": _spy_buy_and_hold(cycles, navs[0]),
            "fixed_five_percent_same_direction": _fixed_size_counterfactual(rows, navs[0]),
        },
        "attribution": rows,
        "round_trips": trades,
        "graduation": {
            "eligible": all(
                (
                    len(trades) >= 200,
                    expectancy_low is not None and expectancy_low > ZERO,
                    sharpe is not None and Decimal(sharpe) > ONE,
                    max_calibration_error < Decimal("0.10"),
                    cost_share is not None and cost_share < Decimal("0.20"),
                )
            ),
            "closed_trades_200": len(trades) >= 200,
            "expectancy_ci_above_zero": expectancy_low is not None and expectancy_low > ZERO,
            "sharpe_above_one": sharpe is not None and Decimal(sharpe) > ONE,
            "calibration_under_ten_points": max_calibration_error < Decimal("0.10"),
            "model_cost_under_twenty_percent_gross_profit": (
                cost_share is not None and cost_share < Decimal("0.20")
            ),
            "paper_only": True,
        },
        "interpretation": (
            "Only recorded cycle marks are used. Intracycle target/stop order is unknown until "
            "the monitor records denser marks; open and sparse outcomes are left unscored."
        ),
    }


def _spy_buy_and_hold(cycles: list[dict[str, Any]], initial_nav: Decimal) -> dict[str, Any]:
    observations: list[tuple[datetime, Decimal]] = []
    for cycle in cycles:
        for quote in cycle.get("quotes", []):
            if str(quote.get("instrument_id")) != "SPY":
                continue
            observations.append((_dt(str(quote["observed_at"])), _dec(quote["price"])))
    observations.sort(key=lambda item: item[0])
    if len(observations) < 2:
        return {
            "status": "unavailable",
            "reason": "No overlapping SPY quotes in the ledger yet.",
        }
    start_price = observations[0][1]
    end_price = observations[-1][1]
    if start_price <= ZERO:
        return {"status": "unavailable", "reason": "SPY start price is non-positive."}
    ret = (end_price / start_price) - ONE
    return {
        "status": "measured",
        "source": "ledger SPY quotes",
        "observations": len(observations),
        "start_price": str(start_price),
        "end_price": str(end_price),
        "buy_and_hold_return": str(ret),
        "nav_if_fully_invested": str(initial_nav * (end_price / start_price)),
    }


def _fixed_size_counterfactual(rows: list[dict[str, Any]], initial_nav: Decimal) -> dict[str, Any]:
    closed = [row for row in rows if row["scored"] and row["mfe"] is not None]
    if not closed:
        return {"status": "unavailable", "reason": "No scored hypotheses with marks."}
    stake = initial_nav * Decimal("0.05")
    # MFE is not used as a return estimate. Win/loss at equal one-unit payoff is
    # intentionally a sizing-only baseline, clearly labeled as such.
    pnl = sum((stake if row["won"] else -stake for row in closed), ZERO)
    return {
        "status": "measured",
        "assumption": "Equal +1/-1 payoff proxy at fixed 5% initial NAV; selection only.",
        "trade_count": len(closed),
        "notional_per_trade": str(stake),
        "pnl_proxy": str(pnl),
    }
