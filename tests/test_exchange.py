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
