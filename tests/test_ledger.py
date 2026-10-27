import sqlite3
from decimal import Decimal as D

import pytest

from nightshift.ledger import Ledger, fold


def test_chain_verifies_and_refuses_edits(ledger):
    ledger.append("forecast", {"market": "kalshi:X", "p_yes": "0.3"})
    assert ledger.verify() == 2
    with pytest.raises(sqlite3.IntegrityError):
        ledger.db.execute("UPDATE events SET data = '{}' WHERE seq = 1")
    with pytest.raises(sqlite3.IntegrityError):
        ledger.db.execute("DELETE FROM events WHERE seq = 2")


def test_tampering_around_the_triggers_breaks_the_chain(tmp_path):
    led = Ledger(tmp_path / "l.db")
    led.append("open", {"cash": "1000"})
    led.append("open", {"cash": "5"})
    led.db.execute("DROP TRIGGER no_update")
    led.db.execute("""UPDATE events SET data = '{"cash":"9999"}' WHERE seq = 1""")
    with pytest.raises(ValueError, match="broken at event 1"):
        led.verify()


def test_fold_tracks_cash_positions_and_settlement():
    events = [
        {"kind": "open", "cash": "1000"},
        {
            "kind": "fill",
            "market": "m",
            "outcome": "YES",
            "side": "buy",
            "shares": "100",
            "cash": "-42",
            "fee": "1",
        },
        {
            "kind": "fill",
            "market": "m",
            "outcome": "YES",
            "side": "sell",
            "shares": "50",
            "cash": "25",
            "fee": "1",
        },
    ]
    acct = fold(events)
    assert acct.cash == D("983")
    pos = acct.positions[("m", "YES")]
    assert pos.shares == 50 and pos.cost == D("21")
    assert acct.fees == 2
    acct = fold(events + [{"kind": "settle", "market": "m", "outcome": "YES", "cash": "50"}])
    assert acct.cash == D("1033") and not acct.positions
