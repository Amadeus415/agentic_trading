"""The simulated exchange: the only code that changes an account.

Orders are market orders filled against the venue's live order book at the
moment they arrive: buys walk the asks, sells walk the bids, whole shares only,
venue taker fees included. What the book cannot fill is not filled. Shares this
account took from a book in the last ten minutes are treated as gone, so one
displayed level cannot be bought twice. Positions are valued at the best bid.

The rules every agent faces, and nothing more: spend only cash you hold, no
shorting (buy the other outcome), and no position may cost more than a quarter
of the account.
"""

from __future__ import annotations

import json
import socketserver
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from nightshift import venues
from nightshift.ledger import Ledger, now_iso
from nightshift.venues import Market, VenueError

MAX_POSITION = Decimal("0.25")
DEPTH_MEMORY = timedelta(minutes=10)
MIN_ORDER = Decimal("1")


class OrderError(ValueError):
    """An order or request the exchange refuses, with a reason the agent can act on."""


def _parse_at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def yes_mid(market: Market) -> Decimal | None:
    """The market's own YES probability: the book midpoint, else the last trade."""
    book = market.books.get("YES")
    if book and book.bid is not None and book.ask is not None:
        return (book.bid + book.ask) / 2
    return market.last_price_yes


class Exchange:
    def __init__(
        self,
        ledger: Ledger,
        *,
        session: int | None = None,
        get_market: Callable[..., Market] = venues.get_market,
        list_markets: Callable[..., list[dict[str, Any]]] = venues.list_markets,
    ) -> None:
        self.ledger = ledger
        self.session = session
        self.get_market = get_market
        self.list_markets = list_markets

    # --- reading ------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        acct = self.ledger.account()
        opened = Decimal(self.ledger.events("open")[0]["cash"])
        keys = list(acct.positions)
        with ThreadPoolExecutor(8) as pool:
            fetched = list(pool.map(self._try_market, [m for m, _ in keys]))
        marks, rows = {}, []
        for key, market in zip(keys, fetched, strict=True):
            pos = acct.positions[key]
            price = self._mark(market, pos.outcome) if market else acct.marks.get(key)
            marks[key] = price if price is not None else Decimal("0")
            rows.append(
                {
                    "market": pos.market,
                    "outcome": pos.outcome,
                    "question": pos.question,
                    "shares": pos.shares,
                    "cost": pos.cost.quantize(Decimal("0.01")),
                    "bid": price,
                    "value": (pos.shares * marks[key]).quantize(Decimal("0.01")),
                    "status": market.status if market else "unavailable",
                    "closes_at": market.closes_at if market else None,
                }
            )
        value = acct.value(marks)
        return {
            "time": now_iso(),
            "cash": acct.cash.quantize(Decimal("0.01")),
            "positions_value": (value - acct.cash).quantize(Decimal("0.01")),
            "account_value": value.quantize(Decimal("0.01")),
            "starting_cash": opened,
            "return_pct": ((value / opened - 1) * 100).quantize(Decimal("0.01")),
            "fees_paid": acct.fees.quantize(Decimal("0.01")),
            "positions": rows,
        }

    def markets(self, **filters: Any) -> list[dict[str, Any]]:
        return self.list_markets(**filters)

    def market(self, market_id: str, depth: int = 10) -> dict[str, Any]:
        m = self.get_market(market_id)
        return {
            "id": m.id,
            "question": m.question,
            "rules": m.rules,
            "url": m.url,
            "event": m.event,
            "closes_at": m.closes_at,
            "status": m.status,
            "payout_yes": m.payout_yes,
            "yes_probability_mid": yes_mid(m),
            "fee": None
            if m.fee_rate is None
            else f"{m.fee_rate} * shares * (price * (1 - price))^{m.fee_exponent}, rounded up",
            "books": {
                outcome: {
                    "bids": [[p, s] for p, s in book.bids[:depth]],
                    "asks": [[p, s] for p, s in book.asks[:depth]],
                }
                for outcome, book in m.books.items()
            },
        }

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        kinds = {"fill", "settle", "forecast"}
        return [e for e in self.ledger.events() if e["kind"] in kinds][-limit:]

    # --- acting -------------------------------------------------------------

    def buy(
        self, market: str, outcome: str, dollars: Any, p_yes: Any, note: str = ""
    ) -> dict[str, Any]:
        """Buy, stating your probability that YES wins (the same scale as `forecast`)."""
        outcome, dollars, p_yes = _outcome(outcome), _dec(dollars, "dollars"), _prob(p_yes)
        if dollars < MIN_ORDER:
            raise OrderError(f"minimum order is ${MIN_ORDER}")
        m = self._open_market(market)
        with self.ledger.transaction():
            acct = self.ledger.account()
            held = acct.positions.get((m.id, outcome))
            invested = acct.cash + sum((pos.cost for pos in acct.positions.values()), Decimal(0))
            room = MAX_POSITION * invested - (held.cost if held else Decimal(0))
            budget = min(dollars, acct.cash, room)
            if budget < MIN_ORDER:
                raise OrderError(
                    f"no room: cash ${acct.cash:.2f}, this position may cost at most "
                    f"${MAX_POSITION * invested:.2f} (25% of the account)"
                )
            asks = self._unconsumed(m.id, outcome, "buy", m.books[outcome].asks)
            shares, spent, fee = _walk(asks, budget, m, buying=True)
            if shares == 0:
                raise OrderError("the book has no asks this budget can fill")
            return self._fill(m, outcome, "buy", shares, spent, fee, note, p_yes=p_yes)

    def sell(self, market: str, outcome: str, shares: Any, note: str = "") -> dict[str, Any]:
        outcome = _outcome(outcome)
        m = self._open_market(market)
        with self.ledger.transaction():
            held = self.ledger.account().positions.get((m.id, outcome))
            if not held:
                raise OrderError(f"you hold no {outcome} shares of {m.id}")
            want = held.shares if str(shares).lower() == "all" else _dec(shares, "shares")
            if want <= 0 or want > held.shares or want != want.to_integral_value():
                raise OrderError(f"sell a whole number of shares up to {held.shares}, or 'all'")
            bids = self._unconsumed(m.id, outcome, "sell", m.books[outcome].bids)
            sold, proceeds, fee = _walk(bids, want, m, buying=False)
            if sold == 0:
                raise OrderError("the book has no bids")
            return self._fill(m, outcome, "sell", sold, proceeds, fee, note)

    def forecast(self, market: str, p_yes: Any, note: str = "") -> dict[str, Any]:
        """Record a probability that YES wins, scored later against the market's own price."""
        p_yes = _prob(p_yes)
        m = self._open_market(market)
        return self.ledger.append(
            "forecast",
            {
                "market": m.id,
                "event": m.event,
                "question": m.question,
                "closes_at": m.closes_at,
                "p_yes": p_yes,
                "market_yes": yes_mid(m),
                "note": note[:2000],
                "session": self.session,
            },
        )

    # --- bookkeeping (the operator's ticker, never the agent) ---------------

    def settle_and_mark(self, cache: dict[str, Market | None] | None = None) -> dict[str, Any]:
        """Pay out resolved positions and record what the rest are worth at the bid."""
        cache = {} if cache is None else cache
        acct = self.ledger.account()
        settled, marks = [], []
        for (market_id, outcome), pos in acct.positions.items():
            m = self._cached(cache, market_id)
            if m and m.status == "resolved":
                payout = m.payout(outcome)
                settled.append(
                    self.ledger.append(
                        "settle",
                        {
                            "market": market_id,
                            "outcome": outcome,
                            "shares": pos.shares,
                            "payout": payout,
                            "cash": pos.shares * payout,
                            "pnl": pos.shares * payout - pos.cost,
                        },
                    )
                )
                continue
            price = self._mark(m, outcome) if m else acct.marks.get((market_id, outcome))
            marks.append(
                {
                    "market": market_id,
                    "outcome": outcome,
                    "shares": pos.shares,
                    "price": price if price is not None else Decimal(0),
                }
            )
        acct = self.ledger.account()
        value = acct.cash + sum((x["shares"] * x["price"] for x in marks), Decimal(0))
        mark = self.ledger.append("mark", {"cash": acct.cash, "value": value, "positions": marks})
        return {"settled": settled, "mark": mark}

    def resolve_forecasts(self, cache: dict[str, Market | None] | None = None) -> list[dict]:
        """Record outcomes for forecast and traded markets that have closed or settled."""
        cache = {} if cache is None else cache
        now = datetime.now(UTC)
        events = self.ledger.events()
        done = {e["market"] for e in events if e["kind"] == "resolve"}
        settled = {e["market"] for e in events if e["kind"] == "settle"}
        due = {
            e["market"]
            for e in events
            if e["kind"] in ("forecast", "fill")
            and e["market"] not in done
            and (
                e["market"] in settled or not e.get("closes_at") or _parse_at(e["closes_at"]) <= now
            )
        }
        resolved = []
        for market_id in sorted(due):
            m = self._cached(cache, market_id)
            if m and m.status == "resolved":
                resolved.append(
                    self.ledger.append("resolve", {"market": market_id, "payout_yes": m.payout_yes})
                )
        return resolved

    # --- internals ----------------------------------------------------------

    def _fill(self, m, outcome, side, shares, gross, fee, note, p_yes=None) -> dict[str, Any]:
        cash = -(gross + fee) if side == "buy" else gross - fee
        book = m.books[outcome]
        return self.ledger.append(
            "fill",
            {
                "market": m.id,
                "event": m.event,
                "question": m.question,
                "closes_at": m.closes_at,
                "outcome": outcome,
                "side": side,
                "shares": shares,
                "price": (gross / shares).quantize(Decimal("0.0001")),
                "fee": fee,
                "cash": cash,
                "p_yes": p_yes,
                "market_yes": yes_mid(m),
                "best_bid": book.bid,
                "best_ask": book.ask,
                "note": note[:2000],
                "session": self.session,
            },
        )

    def _open_market(self, market_id: str) -> Market:
        try:
            m = self.get_market(market_id)
        except VenueError as exc:
            raise OrderError(str(exc)) from exc
        if m.status != "open":
            raise OrderError(f"{m.id} is {m.status}, not open for trading")
        if m.fee_rate is None:
            raise OrderError(f"{m.id} has no published fee schedule; it cannot be priced")
        return m

    def _try_market(self, market_id: str) -> Market | None:
        try:
            return self.get_market(market_id)
        except VenueError:
            return None

    def _cached(self, cache: dict[str, Market | None], market_id: str) -> Market | None:
        if market_id not in cache:
            cache[market_id] = self._try_market(market_id)
        return cache[market_id]

    @staticmethod
    def _mark(m: Market, outcome: str) -> Decimal | None:
        if m.status == "resolved":
            return m.payout(outcome)
        if m.status == "open":
            return m.books[outcome].bid or Decimal(0)
        last = m.last_price_yes
        return None if last is None else (last if outcome == "YES" else 1 - last)

    def _unconsumed(self, market_id, outcome, side, levels):
        """Remove shares this account already took from this side of the book recently."""
        since = datetime.now(UTC) - DEPTH_MEMORY
        taken = sum(
            (
                Decimal(e["shares"])
                for e in self.ledger.events("fill")
                if e["market"] == market_id
                and e["outcome"] == outcome
                and e["side"] == side
                and _parse_at(e["at"]) >= since
            ),
            Decimal(0),
        )
        left = []
        for price, size in levels:
            used = min(size, taken)
            taken -= used
            if size > used:
                left.append((price, size - used))
        return left


def _walk(levels, limit: Decimal, m: Market, *, buying: bool):
    """Fill whole shares level by level. Buying, `limit` is dollars; selling, shares."""
    shares = gross = fee = Decimal(0)
    for price, size in levels:
        size = size.to_integral_value(rounding="ROUND_FLOOR")
        if buying:
            lo, hi = 0, int(size)
            while lo < hi:  # most shares at this level the remaining budget covers
                mid = (lo + hi + 1) // 2
                if gross + fee + mid * price + m.fee(Decimal(mid), price) <= limit:
                    lo = mid
                else:
                    hi = mid - 1
            take = Decimal(lo)
        else:
            take = min(size, limit - shares)
        if take <= 0:
            break
        shares += take
        gross += take * price
        fee += m.fee(take, price)
        if (buying and take < size) or (not buying and shares >= limit):
            break
    return shares, gross, fee


def _outcome(value: str) -> str:
    outcome = str(value).upper()
    if outcome not in venues.OUTCOMES:
        raise OrderError("outcome must be YES or NO")
    return outcome


def _dec(value: Any, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise OrderError(f"{name} must be a number") from exc


def _prob(value: Any) -> Decimal:
    if value is None:
        raise OrderError("state your probability (0 to 1) that YES wins")
    p = _dec(value, "probability")
    if not 0 <= p <= 1:
        raise OrderError("probability must be between 0 and 1")
    return p


# --- serving one agent over a Unix socket -----------------------------------

COMMANDS = ("status", "markets", "market", "buy", "sell", "forecast", "history")


def handle(exchange: Exchange, request: dict[str, Any]) -> dict[str, Any]:
    command, args = request.get("command"), request.get("args") or {}
    if command not in COMMANDS:
        return {"ok": False, "error": f"unknown command; try one of {', '.join(COMMANDS)}"}
    try:
        return {"ok": True, "result": getattr(exchange, command)(**args)}
    except (OrderError, VenueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # a venue hiccup must not drop the agent's connection
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def serve(exchange: Exchange, socket_path: Path) -> socketserver.UnixStreamServer:
    """Answer one JSON request per connection on a background thread."""
    lock = threading.Lock()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            try:
                request = json.loads(self.rfile.readline())
            except json.JSONDecodeError:
                response = {"ok": False, "error": "send one JSON object per line"}
            else:
                with lock:
                    response = handle(exchange, request)
            self.wfile.write((dumps(response) + "\n").encode())

    socket_path.unlink(missing_ok=True)
    server = socketserver.ThreadingUnixStreamServer(str(socket_path), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def dumps(value: Any, indent: int | None = None) -> str:
    return json.dumps(
        value, indent=indent, default=lambda v: float(v) if isinstance(v, Decimal) else str(v)
    )
