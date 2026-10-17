import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from edgecraft.marketdata import KalshiProvider, MarketDataError, PolymarketProvider
from edgecraft.paper_fund import AssetClass, FundMandate, execution_fee
from edgecraft.prediction_scoring import prediction_scores
from edgecraft.scanner import consistency_flags, shortlist

NOW = datetime(2026, 10, 15, tzinfo=UTC)


def mandate():
    return FundMandate.model_validate(
        json.loads(Path("examples/fund.mandate.predictions.json").read_text())["mandate"]
    )


@pytest.mark.parametrize("fee_type", ["quadratic", "quadratic_with_maker_fees"])
def test_kalshi_complement_book_and_venue_fees(monkeypatch, fee_type):
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
    with pytest.raises(MarketDataError, match="not confirmed resolved"):
        PolymarketProvider().quote("polymarket:1:YES", observed_at=NOW)
    market["umaResolutionStatus"] = "resolved"
    assert PolymarketProvider().quote("polymarket:1:YES", observed_at=NOW).status == "settled"


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


def test_scanner_excludes_price_bets_before_fetching():
    class Router:
        def quote(self, *args):
            raise AssertionError("should not fetch")

    report = shortlist(
        [
            {
                "market_id": "1",
                "venue": "polymarket",
                "question": "Bitcoin above 100k?",
                "end_at": "2026-10-16T00:00:00Z",
            }
        ],
        Router(),
        mandate(),
        now=NOW,
    )
    assert not report["candidates"]
    assert report["excluded"][0]["reason"] == "asset_price_bet_requires_reference_model"


def test_cross_venue_match_is_only_a_rule_review_flag():
    rows = [
        dict(
            venue=v,
            question="Will the Fed cut rates?",
            instrument_id=f"{v}:1:YES",
            bid=bid,
            ask=ask,
            entry_fee_per_share="0",
        )
        for v, bid, ask in [("kalshi", "0.7", "0.8"), ("polymarket", "0.4", "0.5")]
    ]
    flags = consistency_flags(rows)
    assert flags[0]["raw_price_gap"] == "0.2"
    assert flags[0]["semantics_verified"] is False


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


def test_scanner_book_budget_reaches_both_venues(monkeypatch):
    from types import SimpleNamespace

    from edgecraft.paper_fund import BookLevel

    requested = []

    class Router:
        def quote(self, instrument, asset):
            requested.append(instrument)
            return SimpleNamespace(
                bids=(BookLevel(price="0.4", size="100"),),
                asks=(BookLevel(price="0.5", size="100"),),
                model_dump=lambda **kwargs: {},
            )

    monkeypatch.setattr("edgecraft.scanner.execution_fee", lambda *args: Decimal("1"))
    markets = [
        dict(
            venue=venue,
            market_id=str(index),
            question="Fed decision?",
            end_at="2026-10-16T00:00:00Z",
        )
        for venue in ("polymarket", "kalshi")
        for index in range(5)
    ]
    report = shortlist(markets, Router(), mandate(), now=NOW, max_books=2)
    assert report["coverage"]["book_markets_attempted"] == 2
    assert {instrument.split(":")[0] for instrument in requested} == {"polymarket", "kalshi"}


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
