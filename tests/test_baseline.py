from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from edgecraft.baseline import BASELINE_FUND_ID, fitted_gamma, run_baseline
from edgecraft.paper_fund import FundMandate, FundQuote, PaperFundLedger
from edgecraft.policy import TradingPolicy

CONFIG = json.loads(Path("examples/fund.mandate.baseline.json").read_text())
MANDATE = FundMandate.model_validate(CONFIG["mandate"])
POLICY = TradingPolicy.model_validate(CONFIG["trading"])


def _market(market_id, bid, ask, *, hours=30, event=None, exclusive=False):
    end = datetime.now(UTC) + timedelta(hours=hours)
    return dict(
        venue="polymarket",
        market_id=market_id,
        event_id=f"polymarket:{event or market_id}",
        event_title=f"Event {event or market_id}",
        mutually_exclusive=exclusive,
        question=f"Will {market_id} happen?",
        rules="Resolves on the official source.",
        end_at=end.isoformat(),
        yes_bid=Decimal(bid),
        yes_ask=Decimal(ask),
        yes_bid_size=None,
        yes_ask_size=None,
        volume_24h=Decimal("100"),
        source_url="https://example.test",
        listing_mid=(Decimal(bid) + Decimal(ask)) / 2,
    )


class Router:
    """Books mirror the listing: NO asks are 1 - YES bids."""

    def __init__(self, markets):
        self.books = {}
        for row in markets:
            bid, ask = row["yes_bid"], row["yes_ask"]
            self.books[f"polymarket:{row['market_id']}:YES"] = (bid, ask)
            self.books[f"polymarket:{row['market_id']}:NO"] = (1 - ask, 1 - bid)
        self.settled: set[str] = set()

    def quote(self, instrument, asset):
        now = datetime.now(UTC)
        bid, ask = self.books[instrument]
        if instrument in self.settled:
            return FundQuote(
                quote_id=f"s-{instrument}-{now.timestamp()}",
                instrument_id=instrument,
                asset_class="prediction",
                price="1",
                observed_at=now,
                source_timestamp=now,
                source_name="test",
                source_url="https://example.test",
                status="settled",
            )
        return FundQuote(
            quote_id=f"q-{instrument}-{now.timestamp()}",
            instrument_id=instrument,
            asset_class="prediction",
            price=(bid + ask) / 2,
            observed_at=now,
            source_timestamp=now,
            source_name="test",
            source_url="https://example.test",
            bids=[{"price": str(bid), "size": "2000"}],
            asks=[{"price": str(ask), "size": "2000"}],
            fee_rate="0.03",
            fee_exponent=1,
            fee_quantum="0.00001",
        )


def _run(tmp_path, monkeypatch, markets, **kwargs):
    monkeypatch.setattr("edgecraft.baseline.discover_markets", lambda **_: markets)
    ledger = PaperFundLedger(tmp_path / "fund.db")
    try:
        ledger.get_mandate(BASELINE_FUND_ID)
    except Exception:
        ledger.initialize(BASELINE_FUND_ID, MANDATE)
    router = kwargs.pop("router", None) or Router(markets)
    result = run_baseline(ledger, BASELINE_FUND_ID, MANDATE, POLICY, router, **kwargs)
    return ledger, router, result


def test_baseline_buys_a_soon_resolving_favorite_and_logs_market_forecasts(tmp_path, monkeypatch):
    markets = [
        _market("fav", "0.94", "0.95"),
        _market("coin", "0.49", "0.51"),
        _market("far", "0.94", "0.95", hours=24 * 60),
    ]
    ledger, _, result = _run(tmp_path, monkeypatch, markets)
    assert result["applied"] is True
    assert [row["instrument_id"] for row in result["accepted"]] == ["polymarket:fav:YES"]
    position = ledger.get_state(BASELINE_FUND_ID).positions[0]
    assert position.playbook_id == "favorite_bias"
    assert position.quantity * position.mark_price <= Decimal("150")  # 15% position cap
    assert result["market_forecasts"] == 3
    assert ledger.verify(BASELINE_FUND_ID).ok
    # Within the interval the next pass is a no-op; known markets are not re-logged.
    _, _, again = _run(tmp_path, monkeypatch, markets)
    assert again["reason"] == "interval_not_elapsed"
    _, _, forced = _run(tmp_path, monkeypatch, markets, force=True)
    assert forced["market_forecasts"] == 0


def test_baseline_locks_in_an_exclusive_no_basket(tmp_path, monkeypatch):
    markets = [
        _market("a", "0.50", "0.52", event="race", exclusive=True),
        _market("b", "0.35", "0.37", event="race", exclusive=True),
        _market("c", "0.25", "0.27", event="race", exclusive=True),
    ]
    ledger, _, result = _run(tmp_path, monkeypatch, markets)
    assert result["applied"] is True
    (basket,) = result["baskets"]
    assert Decimal(basket["locked_edge_per_basket"]) > Decimal("0.05")
    state = ledger.get_state(BASELINE_FUND_ID)
    assert {p.instrument_id for p in state.positions} == {
        "polymarket:a:NO",
        "polymarket:b:NO",
        "polymarket:c:NO",
    }
    assert len({p.quantity for p in state.positions}) == 1
    # The whole basket stays inside the shared-event budget.
    assert sum(p.quantity * p.average_entry for p in state.positions) <= Decimal("300")


def test_baseline_holds_cash_when_nothing_clears_fees(tmp_path, monkeypatch):
    ledger, _, result = _run(tmp_path, monkeypatch, [_market("coin", "0.49", "0.51")])
    assert result["applied"] is False
    assert result["reason"] == "no_edge"
    assert ledger.get_state(BASELINE_FUND_ID).cycle_count == 0


def test_settled_favorites_feed_the_shared_bias_curve(tmp_path, monkeypatch):
    from edgecraft.forecasts import score_forecasts

    markets = [_market(f"m{index}", "0.88", "0.90") for index in range(30)]
    ledger, router, _ = _run(tmp_path, monkeypatch, markets)
    router.settled = {f"polymarket:m{index}:YES" for index in range(30)}
    after_resolution = datetime.now(UTC) + timedelta(days=2)
    scored = score_forecasts(ledger, BASELINE_FUND_ID, router, limit=100, now=after_resolution)
    assert scored["resolved"] == 30
    # Every favorite won, so the fitted curve steepens beyond the prior.
    assert fitted_gamma(ledger, POLICY) > POLICY.baseline_gamma
