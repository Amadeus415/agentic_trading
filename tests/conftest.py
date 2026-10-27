from __future__ import annotations

from decimal import Decimal as D

import pytest

from nightshift.exchange import Exchange
from nightshift.ledger import Ledger
from nightshift.venues import Book, Market, VenueError


def market(
    id="kalshi:TEST-1",
    *,
    status="open",
    payout_yes=None,
    yes_bids=((D("0.40"), D("100")),),
    yes_asks=((D("0.42"), D("50")), (D("0.45"), D("1000"))),
    fee_rate=D("0.07"),
    event="kalshi:TEST",
) -> Market:
    """A YES/NO market whose NO book mirrors the YES book, as on Kalshi."""
    no_bids = tuple((1 - p, q) for p, q in yes_asks)
    no_asks = tuple((1 - p, q) for p, q in yes_bids)
    return Market(
        id=id,
        question=f"Question for {id}?",
        rules="Resolves YES if it happens.",
        url="https://example.com",
        event=event,
        closes_at="2026-11-01T00:00:00Z",
        status=status,
        payout_yes=payout_yes,
        books={"YES": Book(yes_bids, yes_asks), "NO": Book(no_bids, no_asks)}
        if status == "open"
        else {},
        fee_rate=fee_rate,
        last_price_yes=D("0.41"),
    )


class FakeVenues:
    def __init__(self, *markets: Market) -> None:
        self.markets = {m.id: m for m in markets}

    def get(self, market_id: str, books: bool = True) -> Market:
        if market_id not in self.markets:
            raise VenueError(f"unknown market {market_id}")
        return self.markets[market_id]

    def list(self, **filters):
        return [
            {
                "id": m.id,
                "question": m.question,
                "closes_at": m.closes_at,
                "yes_bid": float(m.books["YES"].bid),
                "yes_ask": float(m.books["YES"].ask),
                "volume_24h": 1,
            }
            for m in self.markets.values()
            if m.status == "open"
        ]


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    led.append("open", {"cash": "1000", "run": "test"})
    yield led
    led.close()


@pytest.fixture
def venues():
    return FakeVenues(market())


@pytest.fixture
def exchange(ledger, venues):
    return Exchange(ledger, session=1, get_market=venues.get, list_markets=venues.list)
