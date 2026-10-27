"""Code-only accounts that trade through the same exchange as the agents.

They set the bar without a model. `favorites` buys heavy favorites near
settlement, the classic favorite-longshot bias. `random` buys random outcomes
the same way, which shows what spread and fees alone cost. Each buys at most a
few positions an hour at 5% of the account and holds them to settlement.
"""

from __future__ import annotations

import random as _random
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from nightshift.exchange import Exchange, OrderError

STAKE = Decimal("0.05")
MAX_SPREAD = Decimal("0.03")
PER_HOUR = 3


def _sides(row: dict[str, Any]) -> list[tuple[str, Decimal]]:
    """What buying each outcome costs at the top of a tight listing's book."""
    if row.get("yes_ask") is None or row.get("yes_bid") is None:
        return []
    bid, ask = Decimal(str(row["yes_bid"])), Decimal(str(row["yes_ask"]))
    if ask - bid > MAX_SPREAD:
        return []  # buying a wide spread loses it at once when valued at the bid
    return [(outcome, price) for outcome, price in (("YES", ask), ("NO", 1 - bid)) if 0 < price < 1]


def _buy_each(exchange: Exchange, picks: list[tuple[str, str, Decimal]]) -> int:
    status = exchange.status()
    held = {p["market"] for p in status["positions"]}
    stake = (Decimal(str(status["account_value"])) * STAKE).quantize(Decimal("0.01"))
    bought = 0
    for market, outcome, ask in picks:
        if bought == PER_HOUR or market in held:
            continue
        try:
            # No claimed edge: the stated probability is the price paid.
            p_yes = ask if outcome == "YES" else 1 - ask
            exchange.buy(market, outcome, stake, p_yes=p_yes, note="baseline")
        except OrderError:
            continue
        held.add(market)
        bought += 1
    return bought


def favorites(exchange: Exchange, rng: _random.Random) -> int:
    rows = exchange.markets(max_hours=72, limit=500)
    picks = [
        (row["id"], outcome, ask)
        for row in sorted(rows, key=lambda r: r["closes_at"] or "")
        for outcome, ask in _sides(row)
        if Decimal("0.90") <= ask <= Decimal("0.97")
    ]
    return _buy_each(exchange, picks)


def random(exchange: Exchange, rng: _random.Random) -> int:
    rows = exchange.markets(max_hours=168, limit=500)
    picks = [
        (row["id"], outcome, ask)
        for row in rows
        for outcome, ask in _sides(row)
        if Decimal("0.05") <= ask <= Decimal("0.95")
    ]
    rng.shuffle(picks)
    return _buy_each(exchange, picks)


STRATEGIES: dict[str, Callable[[Exchange, _random.Random], int]] = {
    "favorites": favorites,
    "random": random,
}
