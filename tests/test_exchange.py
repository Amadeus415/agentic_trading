import json
import socket
import tempfile
from decimal import Decimal as D
from pathlib import Path

import pytest
from conftest import FakeVenues, market

from nightshift.exchange import Exchange, OrderError, handle, serve


def test_buy_walks_the_asks_with_fees(exchange, ledger):
    fill = exchange.buy("kalshi:TEST-1", "YES", 100, p_yes=0.6, note="why")
    # 50 shares at 0.42, the rest at 0.45, whole shares, fee rounded up per level.
    assert fill["shares"] == 50 + 167
    assert fill["fee"] == D("0.86") + D("2.90")
    assert -fill["cash"] <= 100
    assert fill["p_yes"] == D("0.6") and fill["market_yes"] == D("0.41")
    assert ledger.account().cash == 1000 + fill["cash"]


def test_buy_needs_a_probability_and_an_open_market(exchange, venues):
    with pytest.raises(OrderError, match="probability"):
        exchange.buy("kalshi:TEST-1", "YES", 10, p_yes=None)
    venues.markets["kalshi:DONE"] = market("kalshi:DONE", status="resolved", payout_yes=D(1))
    with pytest.raises(OrderError, match="not open"):
        exchange.buy("kalshi:DONE", "YES", 10, p_yes=0.5)


def test_position_cap_is_a_quarter_of_the_account(ledger):
    deep = market(yes_bids=((D("0.40"), D("10000")),))
    exchange = Exchange(ledger, get_market=FakeVenues(deep).get)
    fill = exchange.buy("kalshi:TEST-1", "NO", 900, p_yes=0.1)
    assert -fill["cash"] <= 250
    with pytest.raises(OrderError, match="no room"):
        exchange.buy("kalshi:TEST-1", "NO", 50, p_yes=0.1)


def test_recent_fills_use_up_displayed_depth(ledger):
    thin = market(yes_asks=((D("0.42"), D("10")),))
    ex = Exchange(ledger, get_market=FakeVenues(thin).get)
    assert ex.buy(thin.id, "YES", 100, p_yes=0.5)["shares"] == 10
    with pytest.raises(OrderError, match="no asks"):
        ex.buy(thin.id, "YES", 100, p_yes=0.5)


def test_sell_walks_the_bids(exchange, ledger):
    exchange.buy("kalshi:TEST-1", "YES", 20, p_yes=0.6)
    held = ledger.account().positions[("kalshi:TEST-1", "YES")].shares
    fill = exchange.sell("kalshi:TEST-1", "YES", "all")
    assert fill["shares"] == held and fill["price"] == D("0.4")
    assert not ledger.account().positions
    with pytest.raises(OrderError, match="hold no"):
        exchange.sell("kalshi:TEST-1", "YES", 1)


def test_forecast_is_stamped_with_the_market_price(exchange):
    record = exchange.forecast("kalshi:TEST-1", 0.7, note="n")
    assert record["p_yes"] == D("0.7") and record["market_yes"] == D("0.41")


def test_status_values_positions_at_the_bid(exchange):
    exchange.buy("kalshi:TEST-1", "YES", 21, p_yes=0.6)
    status = exchange.status()
    (pos,) = status["positions"]
    assert pos["bid"] == D("0.40") and pos["value"] == pos["shares"] * D("0.40")
    assert status["account_value"] < 1000


def test_settlement_pays_winners_and_marks_the_rest(exchange, venues, ledger):
    exchange.buy("kalshi:TEST-1", "YES", 42, p_yes=0.6)
    venues.markets["kalshi:TEST-1"] = market(status="resolved", payout_yes=D(1))
    result = exchange.settle_and_mark()
    (settled,) = result["settled"]
    assert settled["cash"] == settled["shares"]
    assert ledger.account().cash == result["mark"]["value"]
    assert exchange.resolve_forecasts()[0]["payout_yes"] == D(1)
    assert exchange.resolve_forecasts() == []


def test_socket_round_trip(exchange):
    path = Path(tempfile.mkdtemp(dir="/tmp")) / "x.sock"  # socket paths must stay short
    server = serve(exchange, path)
    try:
        with socket.socket(socket.AF_UNIX) as conn:
            conn.connect(str(path))
            conn.sendall(json.dumps({"command": "status", "args": {}}).encode() + b"\n")
            reply = json.loads(conn.makefile().readline())
    finally:
        server.shutdown()
        server.server_close()
    assert reply["ok"] and reply["result"]["cash"] == 1000.0


def test_unknown_commands_and_bad_args_come_back_as_errors(exchange):
    assert not handle(exchange, {"command": "settle_and_mark"})["ok"]
    assert (
        "unexpected keyword" in handle(exchange, {"command": "status", "args": {"x": 1}})["error"]
    )


def test_the_cap_covers_a_whole_event(ledger):
    a = market("kalshi:A", yes_bids=((D("0.40"), D("10000")),), event="kalshi:ELECTION")
    b = market("kalshi:B", yes_bids=((D("0.40"), D("10000")),), event="kalshi:ELECTION")
    ex = Exchange(ledger, get_market=FakeVenues(a, b).get)
    ex.buy("kalshi:A", "NO", 900, p_yes=0.1)
    with pytest.raises(OrderError, match="no room"):
        ex.buy("kalshi:B", "NO", 100, p_yes=0.1)
    assert ledger.account().positions[("kalshi:A", "NO")].cost <= 250


def test_a_yes_ask_and_a_no_bid_are_the_same_order(ledger):
    thin = market(yes_asks=((D("0.42"), D("10")),), yes_bids=((D("0.40"), D("10")),))
    ex = Exchange(ledger, get_market=FakeVenues(thin).get)
    ex.buy(thin.id, "NO", 100, p_yes=0.1)  # takes the YES bids
    with pytest.raises(OrderError, match="hold no"):
        ex.sell(thin.id, "YES", 1)
    assert ex.buy(thin.id, "YES", 100, p_yes=0.9)["shares"] == 10  # YES asks untouched
    with pytest.raises(OrderError, match="no bids"):
        ex.sell(thin.id, "NO", "all")  # NO bids are the YES asks just taken


def test_forecasts_are_scored_only_against_a_tight_two_sided_book(ledger):
    wide = market("kalshi:WIDE", yes_bids=((D("0.01"), D("50")),), yes_asks=((D("0.25"), D("50")),))
    one_sided = market("kalshi:ONE", yes_bids=())
    ex = Exchange(ledger, get_market=FakeVenues(wide, one_sided).get)
    assert ex.forecast("kalshi:WIDE", 0.05)["market_yes"] is None
    assert ex.forecast("kalshi:ONE", 0.05)["market_yes"] is None


def test_no_trading_after_the_window(ledger, venues):
    ex = Exchange(ledger, ends_at="2020-01-01T00:00:00Z", get_market=venues.get)
    with pytest.raises(OrderError, match="window closed"):
        ex.buy("kalshi:TEST-1", "YES", 10, p_yes=0.5)
    with pytest.raises(OrderError, match="window closed"):
        ex.forecast("kalshi:TEST-1", 0.5)


def test_history_leaves_notes_in_the_ledger(exchange):
    exchange.buy("kalshi:TEST-1", "YES", 10, p_yes=0.6, note="my whole strategy")
    (event,) = exchange.history()
    assert "note" not in event and event["kind"] == "fill"


def test_closed_unpaid_markets_keep_their_last_bid(exchange, venues, ledger):
    exchange.buy("kalshi:TEST-1", "YES", 42, p_yes=0.6)
    exchange.settle_and_mark()
    venues.markets["kalshi:TEST-1"] = market(status="closed")
    mark = exchange.settle_and_mark()["mark"]
    assert mark["positions"][0]["price"] == D("0.40")


def test_settlement_pays_only_shares_held_inside_its_transaction(exchange, venues, ledger):
    held = exchange.buy("kalshi:TEST-1", "YES", 42, p_yes=0.6)["shares"]
    venues.markets["kalshi:TEST-1"] = market(status="resolved", payout_yes=D(1))
    real_fetch = exchange._fetch

    def fetch_then_trade(ids, cache=None):
        fetched = real_fetch(ids, cache)
        if not ledger.events("settle"):  # the agent sells 50 while the ticker is fetching
            sale = {"market": "kalshi:TEST-1", "outcome": "YES", "side": "sell"}
            ledger.append("fill", {**sale, "shares": "50", "cash": "20", "fee": "0"})
        return fetched

    exchange._fetch = fetch_then_trade
    (settled,) = exchange.settle_and_mark()["settled"]
    assert D(settled["shares"]) == held - 50
