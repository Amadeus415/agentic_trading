import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from edgecraft.marketdata import KalshiProvider, MarketDataError, PolymarketProvider
from edgecraft.paper_fund import AssetClass, FundMandate, execution_fee
from edgecraft.policy import TradingPolicy
from edgecraft.prediction_scoring import prediction_scores
from edgecraft.scanner import (
    _kalshi_rows,
    _polymarket_rows,
    cross_venue_flags,
    event_flags,
    prerank,
    shortlist,
)

NOW = datetime(2026, 10, 15, tzinfo=UTC)


def mandate():
    return FundMandate.model_validate(
        json.loads(Path("examples/fund.mandate.facts.json").read_text())["mandate"]
    )


@pytest.mark.parametrize("fee_type", ["quadratic", "quadratic_with_maker_fees"])
def test_kalshi_complement_book_and_venue_fees(monkeypatch, fee_type):
    from edgecraft.marketdata import _kalshi_series

    _kalshi_series.cache_clear()  # Series fee schedules are memoized per process.

    def get(url):
        if url.endswith("/orderbook"):
            return {
                "orderbook_fp": {
                    "yes_dollars": [["0.3", "100"], ["0.4", "200"]],
                    "no_dollars": [["0.5", "150"]],
                }
            }
        if "/series/" in url:
            return {"series": {"fee_type": fee_type, "fee_multiplier": "1"}}
        return {"market": {"status": "active", "event_ticker": "KXFED-26"}}

    monkeypatch.setattr("edgecraft.marketdata._get_json", get)
    quote = KalshiProvider().quote("kalshi:KXCPI-26OCT-T1.0:YES", observed_at=NOW)
    assert quote.price == Decimal("0.45")
    assert min(x.price for x in quote.asks) == Decimal("0.5")
    assert execution_fee(mandate(), quote, Decimal("0.5"), Decimal("100")) == Decimal("1.75")
    assert execution_fee(FundMandate(), quote, Decimal("0.5"), Decimal("100")) == Decimal("0.025")
    no = KalshiProvider().quote("kalshi:KXFED-26:NO", observed_at=NOW)
    assert no.price == Decimal("0.55")


def test_polymarket_mid_does_not_mark_at_buy_price(monkeypatch):
    market = {
        "outcomes": '["Yes","No"]',
        "clobTokenIds": '["1","2"]',
        "feesEnabled": True,
        "feeSchedule": {"rate": "0.04", "exponent": 1},
        "acceptingOrders": True,
    }

    def get(url):
        if "/markets/" in url:
            return market
        assert "/book?" in url
        return {
            "bids": [{"price": "0.3", "size": "100"}],
            "asks": [{"price": "0.5", "size": "100"}],
        }

    monkeypatch.setattr("edgecraft.marketdata._get_json", get)
    quote = PolymarketProvider().quote("polymarket:1:YES", observed_at=NOW)
    assert quote.price == Decimal("0.4")
    market["closed"] = True
    market["outcomePrices"] = '["1","0"]'
    # A closed market without a confirmed resolution is pending, not paid out.
    assert PolymarketProvider().quote("polymarket:1:YES", observed_at=NOW).status == "pending"
    market["umaResolutionStatus"] = "resolved"
    assert PolymarketProvider().quote("polymarket:1:YES", observed_at=NOW).status == "settled"


def test_polymarket_one_sided_or_halted_books_mark_pending(monkeypatch):
    market = {
        "outcomes": '["Yes","No"]',
        "clobTokenIds": '["1","2"]',
        "feesEnabled": False,
        "acceptingOrders": True,
        "outcomePrices": '["0.0005","0.9995"]',
        "umaResolutionStatus": "disputed",
    }
    book = {"bids": [{"price": "0.994", "size": "87"}, {"price": "0.999", "size": "545"}]}

    def get(url):
        return market if "/markets/" in url else book

    monkeypatch.setattr("edgecraft.marketdata._get_json", get)
    # Bids but no asks: worth what a holder could sell for, and not tradable.
    quote = PolymarketProvider().quote("polymarket:1:NO", observed_at=NOW)
    assert (quote.status, quote.price) == ("pending", Decimal("0.999"))
    book["bids"], book["asks"] = [], [{"price": "0.001", "size": "100"}]
    quote = PolymarketProvider().quote("polymarket:1:YES", observed_at=NOW)
    assert (quote.status, quote.price) == ("pending", Decimal("0"))
    # Trading halted before resolution: the venue's displayed price.
    market["acceptingOrders"] = False
    quote = PolymarketProvider().quote("polymarket:1:NO", observed_at=NOW)
    assert (quote.status, quote.price) == ("pending", Decimal("0.9995"))


def test_kalshi_finalized_settles_and_determined_waits(monkeypatch):
    market = {"status": "finalized", "result": "no", "last_price_dollars": "0.0100"}
    monkeypatch.setattr("edgecraft.marketdata._get_json", lambda _url: {"market": market})
    quote = KalshiProvider().quote("kalshi:KXSCORE-26OCT18:NO", observed_at=NOW)
    assert (quote.status, quote.price) == ("settled", Decimal("1"))
    market["status"] = "determined"
    quote = KalshiProvider().quote("kalshi:KXSCORE-26OCT18:NO", observed_at=NOW)
    assert (quote.status, quote.price) == ("pending", Decimal("0.99"))
    market["status"] = "initialized"
    with pytest.raises(MarketDataError, match="not active"):
        KalshiProvider().quote("kalshi:KXSCORE-26OCT18:NO", observed_at=NOW)


def test_scoring_uses_settlement_not_profit_and_deduplicates_refreshes():
    def cycle(at, price, *, settled=False, buy=False):
        return {
            "as_of": at,
            "decision": {
                "journal": {
                    "hypotheses": [{"instrument_id": "p", "p_win": "0.8", "playbook_id": "news"}]
                }
            },
            "quotes": [
                {
                    "instrument_id": "p",
                    "asset_class": "prediction",
                    "price": price,
                    "observed_at": at,
                    "status": "settled" if settled else "open",
                }
            ],
            "fills": [{"instrument_id": "p", "asset_class": "prediction", "side": "buy"}]
            if buy
            else [],
            "audit": {"runtime": {"source_revision": "abc"}},
        }

    cycles = [
        cycle("2026-10-15T00:00:00Z", "0.6", buy=True),
        cycle("2026-10-16T00:00:00Z", "0.7", buy=True),
    ]
    assert prediction_scores(cycles)["summary"]["model_brier"] is None
    cycles.append(cycle("2026-10-17T00:00:00Z", "1", settled=True))
    report = prediction_scores(cycles)
    assert report["summary"]["contracts"] == 1
    assert Decimal(report["summary"]["brier_improvement"]) == Decimal("0.12")
    assert report["contracts"][0]["sampled_clv"] == "0.1"
    assert report["cuts"]["source_revision"][0]["source_revision"] == "abc"


def test_prediction_horizons_extend_without_changing_legacy_limits():
    assert mandate().scheduled_horizon_hours == 8760
    assert FundMandate().scheduled_horizon_hours == 72
    assert mandate().supported_asset_classes == (AssetClass.PREDICTION,)


def test_new_fund_shares_ledger_without_rewriting_old_events_and_retirement_blocks_trades(tmp_path):
    from edgecraft.paper_fund import FundDecision, PaperFundLedger, PaperFundValidationError

    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize("old", FundMandate())
        decision = FundDecision(
            decision_id="d",
            cycle_key="c",
            fund_id="old",
            as_of=NOW,
            action="hold",
            thesis="No edge.",
        )
        ledger.execute_cycle(decision, [])
        old_events = [e.model_dump_json() for e in ledger.list_events("old")]
        ledger.initialize("new", mandate())
        assert [e.model_dump_json() for e in ledger.list_events("old")] == old_events
        assert ledger.get_state("new").nav == 1000
        assert ledger.retire("old")
        assert not ledger.retire("old")
        assert ledger.execute_cycle(decision, []).replayed
        with pytest.raises(PaperFundValidationError, match="retired"):
            ledger.execute_cycle(decision.model_copy(update={"cycle_key": "next"}), [])
        assert ledger.verify("old").ok
        assert ledger.verify("new").ok


def test_prediction_entry_and_settlement_replay_with_long_horizon_and_fee_metadata(tmp_path):
    from datetime import timedelta

    from edgecraft.paper_fund import (
        BookLevel,
        DecisionAction,
        DecisionJournal,
        FundDecision,
        FundEvidence,
        FundHypothesis,
        FundOrder,
        FundQuote,
        PaperFundLedger,
        QuoteStatus,
    )

    evidence = FundEvidence(
        evidence_id="rule",
        observed_at=NOW,
        source_timestamp=NOW,
        source_name="Primary rule",
        source_url="https://example.test/rule",
        claim="Exact settlement source.",
        instrument_ids=("kalshi:FED:YES",),
    )
    belief = FundHypothesis(
        instrument_id="kalshi:FED:YES",
        stance="long",
        statement="Event likely.",
        mechanism="Authoritative release.",
        catalysts=("Release",),
        falsifiers=("Correction",),
        expected_horizon_hours=720,
        confidence="0.8",
        p_win="0.8",
        target_price="1",
        invalidation_price="0.01",
        driver="fed",
        playbook_id="resolution_reading",
        evidence_ids=("rule",),
    )
    journal = DecisionJournal(
        market_regime="Event",
        opportunity_set="Verified rules",
        portfolio_intent="Cash-backed outcome",
        what_changed="Release",
        hypotheses=(belief,),
    )
    decision = FundDecision(
        decision_id="entry",
        cycle_key="entry",
        fund_id="new",
        as_of=NOW,
        action="trade",
        thesis="Rules imply edge",
        evidence=(evidence,),
        journal=journal,
        orders=(
            FundOrder(
                instrument_id="kalshi:FED:YES",
                asset_class="prediction",
                side="buy",
                quantity="100",
                rationale="Rules",
                evidence_ids=("rule",),
            ),
        ),
    )
    quote = FundQuote(
        quote_id="q",
        instrument_id="kalshi:FED:YES",
        asset_class="prediction",
        price="0.45",
        observed_at=NOW,
        source_timestamp=NOW,
        source_name="Kalshi",
        source_url="https://example.test/book",
        bids=(BookLevel(price="0.4", size="100"),),
        asks=(BookLevel(price="0.5", size="100"),),
        fee_rate="0.07",
        fee_exponent=1,
        fee_quantum="0.01",
    )
    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize("new", mandate())
        result = ledger.execute_cycle(decision, [quote], require_brain_journal=True)
        assert result.fills[0].fee == Decimal("1.75")
        assert result.audit.runtime.source_revision
        later = NOW + timedelta(minutes=10)
        settled = quote.model_copy(
            update={
                "quote_id": "settled",
                "price": Decimal(1),
                "status": QuoteStatus.SETTLED,
                "observed_at": later,
                "source_timestamp": later,
            }
        )
        hold = decision.model_copy(
            update={
                "decision_id": "settle",
                "cycle_key": "settle",
                "action": DecisionAction.HOLD,
                "as_of": later,
                "orders": (),
            }
        )
        ledger.execute_cycle(hold, [settled], require_brain_journal=True)
        assert ledger.get_state("new").nav == Decimal("1048.25")
        assert not ledger.get_state("new").positions
        assert ledger.verify("new").ok


def test_legacy_prediction_only_mandate_keeps_flat_fees():
    from edgecraft.paper_fund import FundQuote

    quote = FundQuote(
        quote_id="old",
        instrument_id="old",
        asset_class="prediction",
        price="0.5",
        observed_at=NOW,
        source_timestamp=NOW,
        source_name="Old quote",
        source_url="https://example.test/old",
    )
    legacy = FundMandate(supported_asset_classes=(AssetClass.PREDICTION,))
    assert execution_fee(legacy, quote, Decimal("0.5"), Decimal(100)) == Decimal("0.025")
    assert legacy.scheduled_horizon_hours == 72


def _market(
    market_id="1",
    *,
    venue="polymarket",
    bid="0.40",
    ask="0.42",
    hours=24,
    volume="0",
    question="Will the agency publish the report?",
    event="e1",
    exclusive=False,
):
    end = NOW.timestamp() + hours * 3600
    return dict(
        venue=venue,
        market_id=market_id,
        event_id=f"{venue}:{event}",
        event_title="Agency report",
        mutually_exclusive=exclusive,
        question=question,
        rules="Resolves YES if the agency publishes.",
        end_at=datetime.fromtimestamp(end, UTC).isoformat(),
        yes_bid=Decimal(bid) if bid is not None else None,
        yes_ask=Decimal(ask) if ask is not None else None,
        yes_bid_size=None,
        yes_ask_size=None,
        volume_24h=Decimal(volume),
        source_url="https://example.test",
        listing_mid=None,
    )


class _BookRouter:
    def __init__(self, size="1000"):
        self.size = size
        self.requested = []

    def quote(self, instrument, asset):
        from edgecraft.paper_fund import FundQuote

        self.requested.append(instrument)
        return FundQuote(
            quote_id=f"q-{instrument}",
            instrument_id=instrument,
            asset_class="prediction",
            price="0.41",
            observed_at=NOW,
            source_timestamp=NOW,
            source_name="test",
            source_url="https://example.test",
            bids=[{"price": "0.40", "size": self.size}],
            asks=[{"price": "0.42", "size": self.size}],
            fee_rate="0",
            fee_exponent=1,
            fee_quantum="0.00001",
        )


def test_scanner_excludes_price_bets_and_empty_listings_before_fetching():
    class Router:
        def quote(self, *args):
            raise AssertionError("should not fetch")

    report = shortlist(
        [
            _market("1", question="Bitcoin above 100k?"),
            _market("2", question="XRP Up or Down - 6:30PM ET"),
            _market("3", bid="0", ask="0"),
            _market("4", hours=24 * 400),
        ],
        Router(),
        mandate(),
        TradingPolicy(),
        now=NOW,
    )
    assert not report["candidates"]
    assert report["excluded"] == {
        "asset_price_bet_requires_reference_model": 2,
        "listing_has_no_usable_book": 1,
        "outside_resolution_window": 1,
    }
    assert report["coverage"]["book_markets_attempted"] == 0


def test_rank_prefers_soon_resolving_lightly_watched_markets():
    sides, _ = prerank(
        [
            _market("busy", hours=6, volume="5000000"),
            _market("slow", hours=24 * 60, volume="0"),
            _market("sweet", hours=6, volume="200"),
        ],
        mandate(),
        now=NOW,
    )
    order = list(dict.fromkeys(row["market_id"] for row in sides))
    assert order == ["sweet", "busy", "slow"]


def test_shortlist_reports_executable_terms_and_velocity():
    router = _BookRouter()
    report = shortlist([_market("1", hours=48)], router, mandate(), TradingPolicy(), now=NOW)
    yes = next(row for row in report["candidates"] if row["instrument_id"].endswith(":YES"))
    assert yes["ask"] == "0.42"
    assert Decimal(yes["return_if_wins"]) == pytest.approx(
        Decimal("0.58") / Decimal("0.42"), abs=Decimal("0.000001")
    )
    assert Decimal(yes["annualized_if_wins"]) > 100
    assert report["catalysts"][0]["instrument_id"].startswith("polymarket:1:")


def test_liquidity_is_a_constraint_not_the_goal():
    thin = shortlist([_market("1")], _BookRouter(size="10"), mandate(), TradingPolicy(), now=NOW)
    assert thin["candidates"] == []
    assert thin["excluded"]["spread_or_depth"] == 2


def test_book_budget_counts_markets_not_sides():
    router = _BookRouter()
    report = shortlist(
        [_market(str(i), venue=v) for v in ("polymarket", "kalshi") for i in range(5)],
        router,
        mandate(),
        TradingPolicy(),
        now=NOW,
        max_books=3,
    )
    assert report["coverage"]["book_markets_attempted"] == 3
    assert len(requested := router.requested) == 6
    assert len({instrument.rsplit(":", 1)[0] for instrument in requested}) == 3


def test_exclusive_outcomes_with_bids_over_one_are_flagged_as_no_baskets():
    markets = [
        _market("a", bid="0.50", ask="0.52", exclusive=True),
        _market("b", bid="0.35", ask="0.37", exclusive=True),
        _market("c", bid="0.25", ask="0.27", exclusive=True),
        _market("x", bid="0.60", ask="0.62", event="other"),
        _market("y", bid="0.60", ask="0.62", event="other"),
    ]
    flags = event_flags(markets, mandate(), now=NOW)
    assert len(flags) == 1  # "other" is not known to be mutually exclusive
    assert flags[0]["legs"] == ["polymarket:a:NO", "polymarket:b:NO", "polymarket:c:NO"]
    assert flags[0]["listing_edge_per_basket"] == "0.10"
    assert flags[0]["semantics_verified"] is False


def test_cross_venue_match_is_only_a_rule_review_flag():
    rows = [
        dict(
            venue=v,
            question="Will the Fed cut rates?",
            instrument_id=f"{v}:1:YES",
            bid=bid,
            ask=ask,
        )
        for v, bid, ask in [("kalshi", "0.7", "0.8"), ("polymarket", "0.4", "0.5")]
    ]
    flags = cross_venue_flags(rows)
    assert flags[0]["raw_price_gap"] == "0.2"
    assert flags[0]["semantics_verified"] is False


def test_listing_rows_normalize_both_venues():
    poly = _polymarket_rows(
        [
            {
                "id": "7",
                "outcomes": '["Yes", "No"]',
                "question": "Will it happen?",
                "endDate": "2026-10-20T00:00:00Z",
                "bestBid": 0.3,
                "bestAsk": 0.32,
                "volume24hr": 1200,
                "events": [{"id": "55", "title": "Event", "negRisk": True}],
            },
            {"id": "8", "outcomes": '["Lakers", "Celtics"]'},
        ]
    )
    assert len(poly) == 1
    assert poly[0]["event_id"] == "polymarket:55"
    assert poly[0]["mutually_exclusive"] is True
    assert poly[0]["yes_ask"] == Decimal("0.32")
    kalshi = _kalshi_rows(
        [
            {
                "ticker": "KXT-1",
                "event_ticker": "KXT",
                "title": "Will T?",
                "yes_sub_title": "Above 3",
                "market_type": "binary",
                "yes_bid_dollars": "0.10",
                "yes_ask_dollars": "0.12",
                "volume_24h_fp": "50.00",
                "expected_expiration_time": "2026-10-20T00:00:00Z",
            }
        ]
    )
    assert kalshi[0]["question"] == "Will T? Above 3"
    assert kalshi[0]["mutually_exclusive"] is None


def test_threshold_ladders_are_skipped_without_an_event_lookup(monkeypatch):
    def no_lookup(url):
        raise AssertionError(f"unexpected lookup {url}")

    monkeypatch.setattr("edgecraft.scanner._get_json", no_lookup)
    ladder = [
        _market(
            f"T{strike}", venue="kalshi", bid="0.90", ask="0.92", event="ladder", exclusive=None
        )
        for strike in range(4)
    ]
    assert event_flags(ladder, mandate(), now=NOW) == []
