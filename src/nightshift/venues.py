"""Read-only public market data from Polymarket and Kalshi.

Market IDs are `polymarket:<market id>` or `kalshi:<ticker>`. Every market is
binary; an outcome is YES or NO. Prices are dollars per share that pays $1 if
the outcome wins. No credentials, no order endpoints.
"""

from __future__ import annotations

import functools
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

POLYMARKET = "https://gamma-api.polymarket.com"
POLYMARKET_BOOK = "https://clob.polymarket.com/book"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
OUTCOMES = ("YES", "NO")


class VenueError(RuntimeError):
    """A venue request failed or returned something we cannot price."""


@dataclass(frozen=True)
class Book:
    """Resting orders for one outcome: bids high to low, asks low to high."""

    bids: tuple[tuple[Decimal, Decimal], ...] = ()
    asks: tuple[tuple[Decimal, Decimal], ...] = ()

    @property
    def bid(self) -> Decimal | None:
        return self.bids[0][0] if self.bids else None

    @property
    def ask(self) -> Decimal | None:
        return self.asks[0][0] if self.asks else None


@dataclass(frozen=True)
class Market:
    id: str
    question: str
    rules: str
    url: str
    event: str
    closes_at: str | None
    # open: trading; closed: trading stopped, awaiting resolution; resolved: payout known.
    status: str
    # What one YES share pays once resolved (1, 0, or a venue's split such as 0.5).
    payout_yes: Decimal | None = None
    books: dict[str, Book] = field(default_factory=dict)
    # Taker fee per share is rate * (price * (1 - price)) ** exponent, rounded up to quantum.
    fee_rate: Decimal | None = None
    fee_exponent: int = 1
    fee_quantum: Decimal = Decimal("0.01")
    last_price_yes: Decimal | None = None

    def fee(self, shares: Decimal, price: Decimal) -> Decimal:
        if self.fee_rate is None:
            raise VenueError(f"{self.id}: fee schedule unknown")
        raw = shares * self.fee_rate * (price * (1 - price)) ** self.fee_exponent
        return (raw / self.fee_quantum).to_integral_value(ROUND_CEILING) * self.fee_quantum

    def payout(self, outcome: str) -> Decimal:
        if self.payout_yes is None:
            raise VenueError(f"{self.id} is not resolved")
        return self.payout_yes if outcome == "YES" else 1 - self.payout_yes


def get_json(url: str) -> Any:
    """Every failure (HTTP, network, bad JSON) becomes a VenueError; a timeout is retried once."""
    request = urllib.request.Request(url, headers={"User-Agent": "nightshift-benchmark"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                return json.loads(response.read().decode())
        except Exception as exc:
            timed_out = isinstance(getattr(exc, "reason", exc), TimeoutError)
            if attempt == 2 or not timed_out:
                raise VenueError(f"{url}: {exc}") from exc
    raise AssertionError("unreachable")


def _dec(value: Any) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def _array(value: Any) -> list:
    return json.loads(value) if isinstance(value, str) else list(value or [])


def split_id(market_id: str) -> tuple[str, str]:
    venue, _, key = market_id.partition(":")
    if venue not in ("polymarket", "kalshi") or not key:
        raise VenueError("market IDs look like polymarket:<id> or kalshi:<ticker>")
    return venue, key


def get_market(market_id: str, *, books: bool = True) -> Market:
    venue, key = split_id(market_id)
    return _polymarket(key, books) if venue == "polymarket" else _kalshi(key, books)


# --- Polymarket -------------------------------------------------------------


def _polymarket(key: str, with_books: bool) -> Market:
    m = get_json(f"{POLYMARKET}/markets/{urllib.parse.quote(key)}")
    labels = [str(x).upper() for x in _array(m.get("outcomes"))]
    if labels != ["YES", "NO"]:
        raise VenueError("only YES/NO markets are supported")
    prices = [Decimal(str(p)) for p in _array(m.get("outcomePrices"))]
    event = (m.get("events") or [{}])[0]
    status, payout = "open", None
    if m.get("closed"):
        status = "closed"
        if m.get("umaResolutionStatus") == "resolved" and prices:
            status, payout = "resolved", prices[0]
    elif not m.get("acceptingOrders"):
        status = "closed"
    fee_rate, exponent = None, 1
    if m.get("feesEnabled") is False:
        fee_rate = Decimal("0")
    elif m.get("feesEnabled") and (m.get("feeSchedule") or {}).get("rate") is not None:
        fee_rate = Decimal(str(m["feeSchedule"]["rate"]))
        exponent = int(m["feeSchedule"].get("exponent", 1))
    books: dict[str, Book] = {}
    if with_books and status == "open":
        tokens = _array(m["positionIds"] if m.get("version") == "v2" else m["clobTokenIds"])
        with ThreadPoolExecutor(2) as pool:
            raw = list(pool.map(lambda t: get_json(f"{POLYMARKET_BOOK}?token_id={t}"), tokens))
        for outcome, book in zip(OUTCOMES, raw, strict=True):
            books[outcome] = Book(
                bids=_levels(book.get("bids"), descending=True),
                asks=_levels(book.get("asks"), descending=False),
            )
    return Market(
        id=f"polymarket:{m['id']}",
        question=m.get("question", ""),
        rules=m.get("description", ""),
        url=f"https://polymarket.com/event/{event.get('slug', m.get('slug', ''))}",
        event=f"polymarket:{event.get('id', m['id'])}",
        closes_at=m.get("endDate"),
        status=status,
        payout_yes=payout,
        books=books,
        fee_rate=fee_rate,
        fee_exponent=exponent,
        fee_quantum=Decimal("0.00001"),
        last_price_yes=prices[0] if prices else None,
    )


def _levels(rows: Any, *, descending: bool) -> tuple[tuple[Decimal, Decimal], ...]:
    levels = [(Decimal(str(r["price"])), Decimal(str(r["size"]))) for r in rows or []]
    return tuple(sorted(levels, reverse=descending))


# --- Kalshi -----------------------------------------------------------------


@functools.lru_cache(maxsize=512)
def _kalshi_fee_rate(series: str) -> Decimal | None:
    info = get_json(f"{KALSHI}/series/{urllib.parse.quote(series)}")["series"]
    if info.get("fee_type") not in {"quadratic", "quadratic_with_maker_fees"}:
        return None
    return Decimal("0.07") * Decimal(str(info.get("fee_multiplier", 1)))


def _kalshi(key: str, with_books: bool) -> Market:
    url = f"{KALSHI}/markets/{urllib.parse.quote(key)}"
    m = get_json(url)["market"]
    series = m.get("series_ticker") or str(m["event_ticker"]).split("-")[0]
    status, payout = "open", None
    # "determined" means the outcome is official and payout is only waiting on the clearinghouse.
    if m.get("status") in ("determined", "settled", "finalized") and m.get("result") in (
        "yes",
        "no",
    ):
        status, payout = "resolved", Decimal(int(m["result"] == "yes"))
    elif m.get("status") != "active":
        status = "closed"
    books: dict[str, Book] = {}
    if with_books and status == "open":
        raw = get_json(url + "/orderbook")["orderbook_fp"]
        yes_bids = [(Decimal(p), Decimal(q)) for p, q in raw.get("yes_dollars") or []]
        no_bids = [(Decimal(p), Decimal(q)) for p, q in raw.get("no_dollars") or []]
        # A NO bid at p is a YES ask at 1 - p, and the reverse.
        books["YES"] = Book(
            bids=tuple(sorted(yes_bids, reverse=True)),
            asks=tuple(sorted((1 - p, q) for p, q in no_bids)),
        )
        books["NO"] = Book(
            bids=tuple(sorted(no_bids, reverse=True)),
            asks=tuple(sorted((1 - p, q) for p, q in yes_bids)),
        )
    question = " — ".join(filter(None, [m.get("title"), m.get("yes_sub_title")]))
    return Market(
        id=f"kalshi:{m['ticker']}",
        question=question,
        rules="\n\n".join(filter(None, [m.get("rules_primary"), m.get("rules_secondary")])),
        url=f"https://kalshi.com/markets/{series.lower()}",
        event=f"kalshi:{m['event_ticker']}",
        closes_at=m.get("close_time"),
        status=status,
        payout_yes=payout,
        books=books,
        fee_rate=_kalshi_fee_rate(series) if status == "open" else Decimal("0"),
        last_price_yes=_dec(m.get("last_price_dollars")),
    )


# --- Listings ---------------------------------------------------------------


def list_markets(
    *,
    min_hours: float = 0,
    max_hours: float = 24 * 7,
    venue: str | None = None,
    query: str | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Open binary markets closing inside the window, busiest first.

    Each venue returns a few pages; a text query filters what those pages hold.
    """
    now = now or datetime.now(UTC)
    start, end = now + timedelta(hours=min_hours), now + timedelta(hours=max_hours)
    venues = [venue] if venue else ["polymarket", "kalshi"]
    fetch = {"polymarket": _polymarket_listing, "kalshi": _kalshi_listing}
    with ThreadPoolExecutor(len(venues)) as pool:
        batches = list(pool.map(lambda v: fetch[v](start, end), venues))
    rows = [row for batch in batches for row in batch]
    if query:
        words = query.lower().split()
        rows = [r for r in rows if all(w in r["question"].lower() for w in words)]
    rows.sort(key=lambda r: r["volume_24h"], reverse=True)
    return rows[:limit]


def _polymarket_listing(start: datetime, end: datetime, pages: int = 5) -> list[dict]:
    rows = []
    for page in range(pages):
        params = urllib.parse.urlencode(
            dict(
                active="true",
                closed="false",
                limit=100,
                offset=page * 100,
                end_date_min=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                end_date_max=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                order="volume24hr",
                ascending="false",
            )
        )
        batch = get_json(f"{POLYMARKET}/markets?{params}")
        for m in batch:
            if [str(x).lower() for x in _array(m.get("outcomes"))] != ["yes", "no"]:
                continue
            if not m.get("acceptingOrders"):
                continue
            rows.append(
                dict(
                    id=f"polymarket:{m['id']}",
                    question=m.get("question", ""),
                    closes_at=m.get("endDate"),
                    yes_bid=_num(m.get("bestBid")),
                    yes_ask=_num(m.get("bestAsk")),
                    volume_24h=round(float(m.get("volume24hr") or 0)),
                )
            )
        if len(batch) < 100:
            break
    return rows


def _kalshi_listing(start: datetime, end: datetime, pages: int = 5) -> list[dict]:
    rows, cursor = [], ""
    for _ in range(pages):
        params = urllib.parse.urlencode(
            dict(
                status="open",
                limit=200,
                cursor=cursor,
                mve_filter="exclude",
                min_close_ts=int(start.timestamp()),
                max_close_ts=int(end.timestamp()),
            )
        )
        payload = get_json(f"{KALSHI}/markets?{params}")
        for m in payload["markets"]:
            if m.get("market_type", "binary") != "binary":
                continue
            rows.append(
                dict(
                    id=f"kalshi:{m['ticker']}",
                    question=" — ".join(filter(None, [m.get("title"), m.get("yes_sub_title")])),
                    closes_at=m.get("close_time"),
                    yes_bid=_num(m.get("yes_bid_dollars")),
                    yes_ask=_num(m.get("yes_ask_dollars")),
                    volume_24h=round(float(m.get("volume_24h_fp") or 0)),
                )
            )
        cursor = payload.get("cursor") or ""
        if not cursor:
            break
    return rows


def _num(value: Any) -> float | None:
    return None if value in (None, "") else float(value)
